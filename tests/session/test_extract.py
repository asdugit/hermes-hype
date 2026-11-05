"""Extraction: tool coverage, pairing, stubs, notifications, robustness."""
import base64
import json

from session_synth import Transcript, coding_session, untrusted

from showreel_core.session import extract_events
from showreel_core.session.extract import decode_result


def kinds(res):
    return [e.kind for e in res.events]


def by_kind(res, kind):
    return [e for e in res.events if e.kind == kind]


def test_coding_session_kinds_and_ids():
    res = extract_events(coding_session())
    assert kinds(res) == ["user_prompt", "assistant_note", "todo", "file_write", "terminal", "file_patch", "terminal",
                          "file_read", "tool_other", "final_answer"]
    assert [e.id for e in res.events] == [f"e{i}" for i in range(len(res.events))]
    assert res.events[0].t == 0.0 and all(b.t >= a.t for a, b in zip(res.events, res.events[1:]))
    assert not res.warnings


def test_terminal_ansi_exit_tests_and_fix():
    res = extract_events(coding_session())
    red, green = by_kind(res, "terminal")
    assert red.ok is False and red.data["exit_code"] == 1
    assert red.data["tests"] == {"framework": "pytest", "passed": 10, "failed": 2}
    assert not any("\x1b" in line for line in red.data["output_lines"])
    assert green.ok and green.data["tests"]["passed"] == 12
    assert green.data["fixed"] is True and green.data["tests_green_after_red"] is True
    assert green.weight >= 0.9
    assert green.title == "python -m pytest -q"          # leading "cd … &&" dropped from the title only
    assert green.data["cmd"].startswith("cd C:/Users/alice/proj")


def test_write_then_patch_uses_result_diff():
    res = extract_events(coding_session())
    w = by_kind(res, "file_write")[0]
    assert w.data["new_file"] and w.data["lang"] == "python" and w.data["total_lines"] == 9
    p = by_kind(res, "file_patch")[0]
    assert p.data["path"] == "C:\\Users\\alice\\proj\\summer.py"
    assert (p.data["adds"], p.data["dels"]) == (2, 1)
    assert p.data["synthetic"] is False
    assert p.data["hunks"][0]["header"].startswith("@@ -3,3 +3,4 @@")


def test_patch_replace_mode_without_diff_is_synthesised_and_failure_flagged():
    t = Transcript().user("go")
    t.call("patch", {"path": "a.js", "old_string": "let a = 1;", "new_string": "const a = 1;"},
           {"success": False, "error": "Could not find a match"})
    (p,) = by_kind(extract_events(t.rows), "file_patch")
    assert p.ok is False and p.data["synthetic"] is True
    assert p.data["error"].startswith("Could not find")
    assert (p.data["adds"], p.data["dels"]) == (1, 1)


def test_patch_v4a_multi_file_emits_one_event_per_file():
    patch = "*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+y\n*** Add File: b.py\n+print(1)\n*** End Patch"
    t = Transcript().user("go").call("patch", {"mode": "patch", "patch": patch}, {"success": True})
    evs = by_kind(extract_events(t.rows), "file_patch")
    assert [e.data["path"] for e in evs] == ["a.py", "b.py"]
    assert evs[1].data["action"] == "add" and evs[1].data["new_file"] is True


def test_overwrite_counts_diff_against_known_content():
    t = Transcript().user("go")
    t.call("write_file", {"path": "/srv/x.txt", "content": "a\nb\nc\n"}, {"bytes_written": 6})
    t.call("write_file", {"path": "/srv/x.txt", "content": "a\nB\nc\nd\n"}, {"bytes_written": 8})
    first, second = by_kind(extract_events(t.rows), "file_write")
    assert first.data["new_file"] and not second.data["new_file"]
    assert (second.data["adds"], second.data["dels"]) == (2, 1)


def test_stale_write_is_not_ok():
    t = Transcript().user("go").call("write_file", {"path": "f.py", "content": "x"},
                                     {"error": "Refusing to overwrite", "stale_write_blocked": True})
    (w,) = by_kind(extract_events(t.rows), "file_write")
    assert w.ok is False


def test_long_output_keeps_head_and_tail_verbatim():
    out = "\n".join(f"line {i}" for i in range(500))
    t = Transcript().user("go").call("terminal", {"command": "seq 500"}, {"output": out, "exit_code": 0})
    (ev,) = by_kind(extract_events(t.rows), "terminal")
    lines = ev.data["output_lines"]
    assert len(lines) == 40 and ev.data["output_total"] == 500 and ev.data["output_gap"] == 12
    assert lines[0] == "line 0" and lines[-1] == "line 499"
    assert all(line in out.split("\n") for line in lines)        # verbatim, no inserted marker


def test_binary_junk_and_carriage_returns_cleaned():
    junk = "ok\n" + "\ufffd" * 50 + "\nprogress 10%\rprogress 100%\nend\x07"
    t = Transcript().user("go").call("terminal", {"command": "build"}, {"output": junk, "exit_code": 0})
    (ev,) = by_kind(extract_events(t.rows), "terminal")
    assert ev.data["output_lines"] == ["ok", "progress 100%", "end"]


def test_background_terminal_and_process_completion_notification():
    t = Transcript().user("go")
    t.call("terminal", {"command": "npm run dev", "background": True},
           {"output": "", "exit_code": None, "session_id": "proc_1", "pid": 42})
    t.user("[IMPORTANT: Background process proc_1 completed normally (exit code 0).\nCommand: npm run dev\nOutput:\n"
           "  VITE v5  ready\n  Local:   http://localhost:5173/\n", display_kind="process_complete")
    res = extract_events(t.rows)
    started, done = by_kind(res, "terminal")
    assert started.data["background"] and started.ok
    assert done.data["completion"] and done.data["exit_code"] == 0 and done.data["notification"]
    assert "http://localhost:5173/" in done.data["urls"]
    assert len(by_kind(res, "user_prompt")) == 1                 # the notification is not a user prompt


def test_execute_code_maps_to_python_terminal():
    code = "# Counting rows in the CSV\nimport csv\nprint(sum(1 for _ in csv.reader(open('d.csv'))))"
    t = Transcript().user("go").call("execute_code", {"code": code},
                                     {"status": "success", "output": "41\n", "exit_code": 0, "duration_seconds": 0.2})
    (ev,) = by_kind(extract_events(t.rows), "terminal")
    assert ev.tool == "execute_code" and ev.data["shell"] == "python"
    assert ev.title == "Counting rows in the CSV" and ev.data["cmd"] == "import csv"
    assert ev.data["elapsed_s"] == 0.2 and ev.data["output_lines"] == ["41"]


def test_browser_exec_nav_and_screenshot_paths():
    code = '# Checking the landing page\nnew_tab("http://localhost:3000/")\nwait_for_load()\nprint(capture_screenshot())'
    result = untrusted("browser_exec", json.dumps({"success": True, "exit_code": 0,
                                                   "output": "C:\\\\Users\\\\alice\\\\.cache\\\\shot_1.png\n"}))
    t = Transcript().user("go").call("browser_exec", {"code": code}, result)
    res = extract_events(t.rows)
    (nav,) = by_kind(res, "browser_nav")
    (shot,) = by_kind(res, "screenshot")
    assert nav.data["url"] == "http://localhost:3000/" and nav.title == "Checking the landing page"
    assert shot.data["src"].endswith("shot_1.png") and shot.data["url"] == "http://localhost:3000/"


def test_legacy_browser_tools_and_mcp_generic():
    t = Transcript().user("go")
    t.call("browser_navigate", {"url": "https://example.org"}, {"success": True, "title": "Example"})
    t.call("browser_vision", {"question": "ok?"}, {"success": True, "screenshot_path": "/tmp/cache/screenshots/s.png"})
    t.call("mcp_github_create_issue", {"title": "Bug", "body": "x"}, {"number": 7})
    res = extract_events(t.rows)
    assert by_kind(res, "browser_nav")[0].data["url"] == "https://example.org"
    assert by_kind(res, "screenshot")[0].data["src"] == "/tmp/cache/screenshots/s.png"
    other = by_kind(res, "tool_other")[0]
    assert other.data["mcp_server"] == "github" and other.data["mcp_tool"] == "create_issue"


def test_vision_local_image_is_screenshot_remote_is_other():
    t = Transcript().user("go")
    t.call("vision_analyze", {"image_url": "D:/renders/frame_0001.png", "question": "Is the logo centred?"},
           "Image loaded into your context — you can see it natively now.")
    t.call("vision_analyze", {"image_url": "https://example.org/x.png", "question": "?"}, "Image loaded")
    res = extract_events(t.rows)
    (shot,) = by_kind(res, "screenshot")
    assert shot.data["source"] == "vision_analyze" and shot.data["question"] == "Is the logo centred?"
    assert by_kind(res, "tool_other")[0].data["action"] == "vision"


def test_web_search_and_extract_unwrap_untrusted_json():
    sr = untrusted("web_search", json.dumps({"success": True, "data": {"web": [
        {"url": "https://a.example", "title": "A title", "description": "d"},
        {"url": "https://b.example", "title": "B title", "description": "d"}]}}))
    ex = untrusted("web_extract", json.dumps({"results": [{"url": "https://a.example", "title": "A page",
                                                            "content": "...", "error": None}]}))
    t = Transcript().user("go").call("web_search", {"query": "best waffles"}, sr)
    t.call("web_extract", {"urls": ["https://a.example", "https://b.example"]}, ex)
    res = extract_events(t.rows)
    s = by_kind(res, "web_search")[0]
    assert s.data["query"] == "best waffles" and s.data["titles"] == ["A title", "B title"] and s.data["count"] == 2
    e = by_kind(res, "web_extract")[0]
    assert e.data["titles"] == ["A page"] and "(+1 more)" in e.summary


def test_image_generate_tts_delegate_skill_clarify():
    t = Transcript().user("go")
    t.call("image_generate", {"prompt": "a red fox logo"}, {"success": True, "image": "/home/a/.hermes/cache/images/fox.png"})
    t.call("text_to_speech", {"text": "Hello there"}, {"success": True, "file_path": "/tmp/v.mp3", "media_tag": "MEDIA:/tmp/v.mp3"})
    t.call("delegate_task", {"tasks": [{"goal": "Write docs"}, {"goal": "Write tests"}]},
           {"status": "dispatched", "count": 2, "goals": ["Write docs", "Write tests"]})
    t.call("skill_manage", {"operations": [{"action": "patch", "name": "my-skill"}]}, {"success": True})
    t.call("skill_view", {"name": "pdf"}, {"success": True, "name": "pdf", "content": "..."})
    t.call("clarify", {"questions": [{"question": "Dark or light theme?", "options": ["dark", "light"]}]},
           {"responses": [{"answer": "dark", "status": "answered"}], "outcome": "answered"})
    res = extract_events(t.rows)
    img = by_kind(res, "image_generated")[0]
    assert img.data["src"].endswith("fox.png") and img.data["prompt"] == "a red fox logo" and img.weight >= 0.8
    tts = [e for e in res.events if e.tool == "text_to_speech"][0]
    assert tts.data["audio"] == "/tmp/v.mp3"
    d = by_kind(res, "delegate")[0]
    assert d.data["goals"] == ["Write docs", "Write tests"] and d.data["count"] == 2
    sk = by_kind(res, "skill")
    assert sk[0].data["names"] == ["my-skill"] and sk[1].data["action"] == "view"
    c = by_kind(res, "clarify")[0]
    assert c.data["questions"] == ["Dark or light theme?"] and c.data["answers"] == ["dark"]


def test_tool_call_wrapper_single_and_multi():
    t = Transcript().user("go")
    t.call("tool_call", {"calls": [{"name": "todo_list", "arguments": {"todos": [
        {"id": "1", "content": "Ship it", "status": "completed"}]}}]},
        {"todos": [{"id": "1", "content": "Ship it", "status": "completed"}]})
    t.call("tool_call", {"calls": json.dumps([{"name": "process_manage", "arguments": {"action": "kill"}},
                                              {"name": "process_manage", "arguments": {"action": "list"}}])},
           json.dumps([{"status": "killed"}, {"processes": []}]))
    res = extract_events(t.rows)
    (todo,) = by_kind(res, "todo")
    assert todo.tool == "todo_list" and todo.data["done"] == 1
    others = [e for e in res.events if e.tool == "process_manage"]
    assert len(others) == 2


def test_process_manage_wait_becomes_background_terminal():
    t = Transcript().user("go").call("process_manage", {"action": "wait", "session_id": "p1"},
                                     {"status": "exited", "command": "pytest -q", "exit_code": 0,
                                      "output": "5 passed in 0.1s"})
    (ev,) = by_kind(extract_events(t.rows), "terminal")
    assert ev.data["completion"] and ev.data["tests"]["passed"] == 5


def test_compaction_stubs_and_summary_rows():
    t = Transcript().user("go")
    t.call("terminal", {"command": "make build"}, "[terminal] ran `make build` -> exit 2, 40 lines output")
    t.call("write_file", {"path": "x.py", "content": "print(1)\n"}, "[write_file] wrote to x.py (1 lines)")
    t.call("read_file", {"path": "big.py"}, "[read_file output demoted at compaction — 5,025 chars preserved in session history.]")
    t.call("search_files", {"pattern": "x"}, "[Duplicate tool output — same content as a more recent call]")
    t.user("[CONTEXT COMPACTION — REFERENCE ONLY] Earlier turns were compacted into the summary below.",
           _compressed_summary=True)
    res = extract_events(t.rows)
    term = by_kind(res, "terminal")[0]
    assert term.data["stub"] and term.data["exit_code"] == 2 and term.ok is False and term.data["output_lines"] == []
    w = by_kind(res, "file_write")[0]
    assert w.data["stub"] and w.data["lines"] == ["print(1)"] and w.ok   # args survive compaction verbatim
    assert by_kind(res, "file_read")[0].data["stub"]
    assert [e for e in res.events if e.tool == "search_files"][0].data["stub"]
    note = [e for e in by_kind(res, "assistant_note") if e.data.get("compaction")]
    assert note and note[0].data["stub"] and note[0].data["text"] == ""
    assert len(by_kind(res, "user_prompt")) == 1


def test_steer_system_notes_and_cron_fallback():
    t = Transcript()
    t.user("[OUT-OF-BAND USER MESSAGE — a direct message]\nUse blue instead\n[/OUT-OF-BAND USER MESSAGE]",
           display_kind="steer")
    t.user("[System: Your previous response was empty]")
    res = extract_events(t.rows)
    (p,) = by_kind(res, "user_prompt")
    assert p.data["text"] == "Use blue instead" and p.data["steer"] is True

    cron = Transcript().user("[IMPORTANT: You are running as a scheduled cron job. Check the weather.]").say("Sunny.")
    res2 = extract_events(cron.rows)
    assert res2.events[0].kind == "user_prompt" and res2.events[0].data["synthetic"]


def test_display_text_preferred_for_user_prompt():
    t = Transcript().user("expanded @file content ...", display_metadata={"display_text": "fix @app.py"})
    assert extract_events(t.rows).events[0].data["text"] == "fix @app.py"


def test_delegation_complete_notification():
    text = ("[ASYNC DELEGATION BATCH COMPLETE — deleg_1]\nA background fan-out unit...\n\n"
            "--- ✓ TASK 1/2: Write docs\nresult...\n--- ✗ TASK 2/2: Write tests\nerror...")
    res = extract_events(Transcript().user("go").user(text, display_kind="async_delegation_complete").rows)
    (d,) = by_kind(res, "delegate")
    assert d.data["completed"] and d.data["count"] == 2 and d.data["succeeded"] == 1 and d.ok is False


def test_final_answer_media_becomes_deliverable_screenshot():
    t = Transcript().user("make a poster").say("Here it is:\nMEDIA:/home/a/out/poster.png\nEnjoy!")
    res = extract_events(t.rows)
    assert res.events[-2].kind == "final_answer" and res.events[-2].data["media"] == ["/home/a/out/poster.png"]
    shot = res.events[-1]
    assert shot.kind == "screenshot" and shot.data["artifact"] and shot.weight >= 0.9


def test_multimodal_tool_content_inline_image():
    png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 30).decode()
    parts = [{"type": "text", "text": "capture mode=som 800x600"},
             {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}}]
    t = Transcript().user("go").call("computer_use", {"action": "capture"}, parts)
    (shot,) = by_kind(extract_events(t.rows), "screenshot")
    assert shot.data["_inline_b64"] == png and shot.data["source"] == "desktop"


def test_unanswered_call_and_orphan_tool_row():
    t = Transcript().user("go").call("terminal", {"command": "sleep 100"}, None)
    t.rows.append({"id": 99, "role": "tool", "content": "late", "tool_call_id": "ghost", "tool_name": "terminal",
                   "timestamp": t.t + 1, "tool_calls": []})
    res = extract_events(t.rows)
    assert res.unanswered_calls == 1 and res.unpaired_results == 1
    assert by_kind(res, "terminal")[0].data["output_lines"] == []


def test_malformed_rows_never_raise():
    rows = [{"role": "assistant", "content": None, "tool_calls": [{"function": {"name": "terminal", "arguments": "{bad"}}]},
            {"role": "tool", "content": b"\xff\xfe", "tool_call_id": None},
            {"role": "user", "content": {"type": "text", "text": "hi"}, "timestamp": "nope"},
            {"role": "assistant", "content": [{"type": "text", "text": "ok"}], "tool_calls": "not-a-list"}]
    res = extract_events(rows)
    assert any(e.kind == "terminal" for e in res.events)
    assert res.events[-1].kind == "final_answer"


def test_non_ascii_and_failed_tool_errors():
    t = Transcript().user("Привет, сделай сайт 🚀")
    t.call("terminal", {"command": "echo ünïcödé"}, "Error executing tool 'terminal': timed out after 420.0s")
    res = extract_events(t.rows)
    assert res.events[0].data["text"].startswith("Привет")
    term = by_kind(res, "terminal")[0]
    assert term.ok is False


def test_decode_result_variants():
    assert decode_result(None, "x").missing
    r = decode_result({"content": "Tool 'process_manage' does not exist. Available tools: a"}, "process_manage")
    assert r.failed
    r = decode_result({"content": "<persisted-output>\nThis tool result was too large.\nFull output saved to: /c/spill.txt\n"}, "t")
    assert r.spilled_path == "/c/spill.txt"
    r = decode_result({"content": "[skill_view] name=pdf (5,620 chars) [SKILL_PRUNED: content lost]"}, "skill_view")
    assert r.stub
    r = decode_result({"content": "[1] first item\n[2] second"}, "terminal")
    assert not r.stub                                              # real output that starts with "["
