"""Reader: read-only sqlite fallback, SessionDB feature detection, session listing."""
import hashlib
import sys
import types

from session_synth import Transcript, coding_session, make_state_db

from showreel_core.session import reader


def _hash(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_sqlite_fallback_decodes_rows_and_never_writes(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_state", None)          # force ImportError → sqlite backend
    rows = coding_session()
    rows[1]["content"] = [{"type": "text", "text": "multimodal note"}]
    db = make_state_db(tmp_path / "state.db", {"s1": rows})
    before = _hash(db)
    data = reader.read_session("s1", db)
    assert data.backend == "sqlite" and any("SessionDB unavailable" in w for w in data.warnings)
    assert len(data.rows) == len(rows)
    assert data.rows[1]["content"] == [{"type": "text", "text": "multimodal note"}]   # \x00json: decoded
    call_row = next(r for r in data.rows if r["tool_calls"])
    assert isinstance(call_row["tool_calls"], list) and call_row["tool_calls"][0]["function"]["name"]
    assert data.meta["model"] == "test-model"
    assert _hash(db) == before
    assert not (tmp_path / "state.db-wal").exists() or (tmp_path / "state.db-wal").stat().st_size == 0


def test_display_order_dedupe_prefers_live_row(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_state", None)
    t = Transcript().user("hello").say("first answer")
    rows = t.rows
    rows[1].update(active=0, compacted=1)                            # archived by compaction ...
    extra = [{"session_id": "s1", "role": "assistant", "content": "live copy", "timestamp": rows[1]["timestamp"],
              "active": 1, "compacted": 0, "display_order": 1},     # ... re-inserted live in the same slot
             {"session_id": "s1", "role": "assistant", "content": "rewound", "timestamp": rows[1]["timestamp"] + 1,
              "active": 0, "compacted": 0, "display_order": 7}]     # undo/rewind row: never shown
    db = make_state_db(tmp_path / "state.db", {"s1": rows}, extra_rows=extra)
    got = [r["content"] for r in reader.load_transcript("s1", db)]
    assert got == ["hello", "live copy"]


def test_missing_db_returns_empty_with_warning(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_state", None)
    data = reader.read_session("nope", tmp_path / "missing.db")
    assert data.rows == [] and data.backend == "" and data.warnings
    assert reader.load_transcript("nope", tmp_path / "missing.db") == []


def test_list_recent_and_resolve(tmp_path):
    db = make_state_db(tmp_path / "state.db", {"20261101_aaa": coding_session(), "20261102_bbb": coding_session()})
    recent = reader.list_recent_sessions(5, db)
    assert [s["id"] for s in recent] == ["20261102_bbb", "20261101_aaa"]
    assert reader.resolve_session_ref("latest", db) == "20261102_bbb"
    assert reader.resolve_session_ref("20261101", db) == "20261101_aaa"
    assert reader.resolve_session_ref("2026", db) is None            # ambiguous prefix
    assert reader.list_recent_sessions(5, tmp_path / "missing.db") == []


def _fake_hermes_state(get_messages, read_only=True):
    """A stand-in ``hermes_state`` module whose ``get_messages`` has exactly the given signature."""
    calls = {}

    def init_ro(self, db_path=None, read_only=False):
        calls["init"] = {"db_path": db_path, "read_only": read_only}

    def init_rw(self, db_path=None):
        calls["init"] = {"db_path": db_path}

    def get_session(self, sid):
        return {"id": sid, "model": "fake-model", "source": "cli"}

    def close(self):
        calls["closed"] = True

    session_db = type("SessionDB", (), {"__init__": init_ro if read_only else init_rw, "get_messages": get_messages,
                                        "get_session": get_session, "close": close})
    mod = types.ModuleType("hermes_state")
    setattr(mod, "SessionDB", session_db)
    return mod, calls


def test_sessiondb_kwargs_are_feature_detected(tmp_path, monkeypatch):
    seen = {}

    def old_api(self, session_id, include_compacted=False):          # no include_ancestors (older Hermes)
        seen["kw"] = {"include_compacted": include_compacted}
        return [{"role": "user", "content": "\x00json:[{\"type\": \"text\", \"text\": \"hi\"}]", "timestamp": 1.0}]

    mod, calls = _fake_hermes_state(old_api)
    monkeypatch.setitem(sys.modules, "hermes_state", mod)
    db = make_state_db(tmp_path / "state.db", {"s1": coding_session()})
    data = reader.read_session("s1", db)
    assert data.backend == "sessiondb"
    assert calls["init"]["read_only"] is True
    assert seen["kw"] == {"include_compacted": True}
    assert data.rows[0]["content"] == [{"type": "text", "text": "hi"}] and calls["closed"]


def test_sessiondb_without_read_only_is_refused(tmp_path, monkeypatch):
    mod, calls = _fake_hermes_state(lambda self, session_id: [], read_only=False)
    monkeypatch.setitem(sys.modules, "hermes_state", mod)
    db = make_state_db(tmp_path / "state.db", {"s1": coding_session()})
    data = reader.read_session("s1", db)
    assert data.backend == "sqlite" and "init" not in calls


def test_sessiondb_error_falls_back_to_sqlite(tmp_path, monkeypatch):
    def broken(self, session_id, include_compacted=False, include_ancestors=False):
        raise RuntimeError("storage refactor")

    mod, _ = _fake_hermes_state(broken)
    monkeypatch.setitem(sys.modules, "hermes_state", mod)
    db = make_state_db(tmp_path / "state.db", {"s1": coding_session()})
    data = reader.read_session("s1", db)
    assert data.backend == "sqlite" and len(data.rows) == len(coding_session())
    assert any("sessiondb read failed" in w for w in data.warnings)


def test_ro_uri_handles_spaces_and_non_ascii(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "hermes_state", None)
    d = tmp_path / "dír with spaces #1"
    d.mkdir()
    db = make_state_db(d / "state.db", {"s1": coding_session()})
    assert len(reader.load_transcript("s1", db)) == len(coding_session())
