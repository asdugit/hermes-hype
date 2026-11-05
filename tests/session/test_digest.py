"""Digest size bounds/structure and the inspect CLI end to end (synthetic DB)."""
import re

from session_synth import Transcript, coding_session, make_state_db

from showreel_core.session import analyze_rows, compute_stats, estimate_tokens, extract_events
from showreel_core.session.digest import build_digest, fmt_t
from showreel_core.session.inspect import main


def huge_session(n_calls=600):
    t = Transcript().user("Refactor the whole monorepo. " * 40)
    for i in range(n_calls):
        k = i % 6
        if k == 0:
            t.call("read_file", {"path": f"/repo/pkg{i % 40}/mod{i}.py"}, {"content": "1|x", "total_lines": 1})
        elif k == 1:
            t.call("terminal", {"command": f"rg -n 'symbol_{i}' /repo"}, {"output": f"/repo/a.py:{i}: hit\n" * 30, "exit_code": 0})
        elif k == 2:
            t.call("patch", {"path": f"/repo/pkg{i % 40}/mod{i}.py", "old_string": "a\n" * 5, "new_string": "b\n" * (i % 30 + 1)},
                   {"success": True})
        elif k == 3:
            t.call("search_files", {"pattern": f"def f{i}", "path": "/repo"}, {"total_count": i})
        elif k == 4:
            t.call("write_file", {"path": f"/repo/new/file{i}.ts", "content": "export const x = 1;\n" * (i % 50 + 1)},
                   {"bytes_written": 10})
        else:
            t.call("web_search", {"query": f"how to fix error {i}"}, "<untrusted_tool_result source=\"web_search\">\n{}\n</untrusted_tool_result>")
        if i % 50 == 49:
            t.say(f"Progress note {i}: " + "details " * 40, dt=1)
            t.user(f"keep going {i}")
    t.say("All done. " + "Summary line. " * 200)
    return t.rows


def test_digest_bounded_for_huge_sessions():
    rows = huge_session()
    b = analyze_rows(rows, {"title": "big", "model": "m"})
    assert len(b.events) > 600
    tokens = estimate_tokens(b.digest)
    assert tokens <= 8000, tokens
    assert "## FIRST REQUEST [e0]" in b.digest and "## FINAL ANSWER" in b.digest and "## TIMELINE" in b.digest
    assert re.search(r"\[e\d+–e\d+\] \S+ \d+ steps:", b.digest)                    # collapsed ranges
    small = analyze_rows(rows, {"title": "big"}, max_tokens=2500)
    assert estimate_tokens(small.digest) <= 2600


def test_digest_lists_every_event_for_small_sessions():
    rows = coding_session()
    events = extract_events(rows).events
    d = build_digest(events, compute_stats(events, rows), {"title": "t"})
    for ev in events:
        assert f"[{ev.id}]" in d or f"[{ev.id}–" in d or f"–{ev.id}]" in d
    assert "FIXED after failure" in d and "12 passed" in d
    assert "## PRODUCT EVIDENCE" not in d                                           # only when a report is given


def test_fmt_t():
    assert fmt_t(0) == "00:00" and fmt_t(75) == "01:15" and fmt_t(3725) == "1:02:05"


def test_inspect_cli_end_to_end(tmp_path, capsys):
    db = make_state_db(tmp_path / "state.db", {"20261106_x": coding_session()})
    out_json = tmp_path / "events.json"
    assert main(["latest", "--db", str(db), "--json", str(out_json), "--assets", str(tmp_path / "assets")]) == 0
    text = capsys.readouterr().out
    assert "# SESSION DIGEST" in text and "kinds:" in text and "product:" in text and "stats:" in text
    assert out_json.exists() and '"events"' in out_json.read_text(encoding="utf-8")
    assert "alice" not in out_json.read_text(encoding="utf-8")                      # home dirs redacted
    assert main(["no-such-session", "--db", str(db)]) == 2
    assert main(["--list", "3", "--db", str(db)]) == 0
