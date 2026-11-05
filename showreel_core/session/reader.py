"""Read-only access to Hermes session transcripts (SPEC 2, research/hermes-platform.md section 3).

This module is the ONLY place that knows how transcripts are stored. If the storage
refactor (SessionDB stand-in) changes the API, adapt ``_SessionDBBackend`` here and
nothing else moves.

Two backends, tried in order:
1. ``hermes_state.SessionDB(read_only=True)`` (public module; imported lazily). Keyword
   arguments of ``get_messages`` are feature-detected with :func:`inspect.signature`.
2. Raw read-only SQLite (``file:...?mode=ro``) mirroring SessionDB's display projection.
   Used only when the import fails or the API looks unfamiliar.

Nothing here ever writes to the database.
"""
from __future__ import annotations

import inspect
import json
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONTENT_JSON_PREFIX = "\x00json:"
_SESSION_META_KEYS = (
    "id", "source", "title", "model", "started_at", "ended_at", "end_reason", "parent_session_id",
    "message_count", "tool_call_count", "last_activity_at", "cwd", "git_repo_root", "git_branch",
)


@dataclass
class SessionData:
    """A transcript plus the session row and provenance of the read."""
    session_id: str
    rows: list[dict[str, Any]]
    meta: dict[str, Any] = field(default_factory=dict)
    backend: str = ""                     # "sessiondb" | "sqlite"
    warnings: list[str] = field(default_factory=list)


class SessionReadError(RuntimeError):
    """Raised by the internal helpers; public helpers convert it into ``SessionData.warnings``."""


# --------------------------------------------------------------------------- paths

def hermes_home() -> Path:
    """Active Hermes home: ``hermes_constants`` when importable, else env/platform default."""
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import-not-found]
        return Path(get_hermes_home())
    except Exception:
        pass
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def default_db_path() -> Path:
    """``<hermes home>/state.db``."""
    return hermes_home() / "state.db"


def _ro_uri(path: Path) -> str:
    # as_posix keeps drive letters ("C:/..."); quote characters that would end the path part.
    p = path.resolve().as_posix().replace("?", "%3f").replace("#", "%23")
    if not p.startswith("/"):
        p = "/" + p
    return f"file:{p}?mode=ro"


def _connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SessionReadError(f"database not found: {path}")
    conn = sqlite3.connect(_ro_uri(path), uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = 1")
    return conn


# ------------------------------------------------------------------------ row shape

def _decode_content(value: Any) -> Any:
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str) and value.startswith(CONTENT_JSON_PREFIX):
        try:
            return json.loads(value[len(CONTENT_JSON_PREFIX):])
        except ValueError:
            return value
    return value


def _decode_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    try:
        out = json.loads(value)
        if isinstance(out, str):          # pre-guard rows are double-encoded
            out = json.loads(out)
        return out
    except (ValueError, TypeError):
        return default


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce one message row (from either backend) into the shape the extractor expects."""
    msg = dict(row)
    msg["content"] = _decode_content(msg.get("content"))
    tc = _decode_json(msg.get("tool_calls"), [])
    msg["tool_calls"] = tc if isinstance(tc, list) else []
    meta = _decode_json(msg.get("display_metadata"), None)
    msg["display_metadata"] = meta if isinstance(meta, dict) else None
    msg["_compressed_summary"] = bool(msg.get("_compressed_summary"))
    ts = msg.get("timestamp")
    try:
        msg["timestamp"] = float(ts) if ts is not None else None
    except (TypeError, ValueError):
        msg["timestamp"] = None
    for key in list(msg):
        if isinstance(msg[key], (bytes, bytearray)):
            msg.pop(key)
    return msg


# ------------------------------------------------------------------ SessionDB backend

def _call_with_supported_kwargs(fn: Any, *args: Any, **wanted: Any) -> Any:
    """Call ``fn`` passing only the keyword arguments its signature accepts."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args)
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(*args, **wanted)
    return fn(*args, **{k: v for k, v in wanted.items() if k in params})


class _SessionDBBackend:
    """Adapter over ``hermes_state.SessionDB``; refuses to open anything not read-only."""
    name = "sessiondb"

    def __init__(self, db_path: Path) -> None:
        from hermes_state import SessionDB  # type: ignore[import-not-found]  # lazy, public module
        if "read_only" not in inspect.signature(SessionDB).parameters:
            raise SessionReadError("SessionDB has no read_only parameter; refusing to open it")
        self._db = SessionDB(db_path=db_path, read_only=True)

    def close(self) -> None:
        try:
            self._db.close()
        except Exception:
            pass

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        return _call_with_supported_kwargs(
            self._db.get_messages, session_id, include_compacted=True, include_ancestors=True)

    def session(self, session_id: str) -> dict[str, Any] | None:
        getter = getattr(self._db, "get_session", None)
        return getter(session_id) if getter else None


# ---------------------------------------------------------------- raw sqlite backend

class _SqliteBackend:
    """Schema-coupled fallback that mirrors SessionDB's display projection, read-only."""
    name = "sqlite"

    def __init__(self, db_path: Path) -> None:
        self._conn = _connect_ro(db_path)
        self._msg_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(messages)")}
        self._sess_cols = {r[1] for r in self._conn.execute("PRAGMA table_info(sessions)")}
        if not {"session_id", "role", "content"} <= self._msg_cols:
            raise SessionReadError("unrecognised messages schema")

    def close(self) -> None:
        self._conn.close()

    def session(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def _lineage(self, session_id: str) -> list[str]:
        """Root → tip over parents that ended by compression (rotation-style compaction)."""
        chain = [session_id]
        if not {"parent_session_id", "end_reason"} <= self._sess_cols:
            return chain
        current = self.session(session_id)
        while current and current.get("parent_session_id") and len(chain) < 100:
            parent = self.session(current["parent_session_id"])
            if not parent or parent["id"] in chain or "compress" not in str(parent.get("end_reason") or ""):
                break
            chain.append(parent["id"])
            current = parent
        return list(reversed(chain))

    def _visible_clause(self) -> str:
        if {"active", "compacted"} <= self._msg_cols:
            return " AND (active = 1 OR compacted = 1)"
        if "active" in self._msg_cols:
            return " AND active = 1"
        return ""

    def _segment(self, session_id: str) -> list[dict[str, Any]]:
        clause = self._visible_clause()
        rows = [dict(r) for r in self._conn.execute(
            f"SELECT * FROM messages WHERE session_id = ?{clause} ORDER BY id ASC", (session_id,))]
        if "display_order" in self._msg_cols and rows and all(r.get("display_order") is not None for r in rows):
            # One row per display slot: prefer the live (active) row, then the newest copy.
            best: dict[Any, dict[str, Any]] = {}
            for r in rows:
                key = r["display_order"]
                cur = best.get(key)
                if cur is None or (r.get("active", 0), r["id"]) > (cur.get("active", 0), cur["id"]):
                    best[key] = r
            rows = [best[k] for k in sorted(best)]
        else:
            rows = _dedupe_generations(rows)
        return [r for r in rows if not _model_only(r)]

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for sid in self._lineage(session_id):
            out.extend(self._segment(sid))
        return out

    def recent(self, limit: int) -> list[dict[str, Any]]:
        cols = [c for c in _SESSION_META_KEYS if c in self._sess_cols]
        order = "COALESCE(last_activity_at, started_at)" if "last_activity_at" in self._sess_cols else "started_at"
        sql = f"SELECT {', '.join(cols)} FROM sessions ORDER BY {order} DESC LIMIT ?"
        return [dict(r) for r in self._conn.execute(sql, (int(limit),))]


def _model_only(row: dict[str, Any]) -> bool:
    meta = _decode_json(row.get("display_metadata"), None)
    return isinstance(meta, dict) and bool(meta.get("model_only"))


def _dedupe_generations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Legacy stores without display_order: drop exact re-inserted copies, keep first position."""
    seen: dict[tuple[Any, ...], int] = {}
    out: list[dict[str, Any]] = []
    for r in rows:
        key = (r.get("role"), r.get("tool_call_id"), r.get("content"), r.get("tool_calls"))
        if key in seen:
            if r.get("active"):
                out[seen[key]] = r
            continue
        seen[key] = len(out)
        out.append(r)
    return out


# ------------------------------------------------------------------------ public API

def _open_backends(db_path: Path, warnings: list[str]) -> list[Any]:
    backends: list[Any] = []
    try:
        backends.append(_SessionDBBackend(db_path))
    except Exception as exc:  # ImportError, API drift, locked DB...
        warnings.append(f"SessionDB unavailable ({type(exc).__name__}: {exc}); using read-only sqlite")
    return backends


def read_session(session_id: str, db_path: str | Path | None = None) -> SessionData:
    """Load a whole session (rows + session metadata). Never raises; problems go to ``warnings``."""
    path = Path(db_path) if db_path else default_db_path()
    data = SessionData(session_id=session_id, rows=[])
    backends = _open_backends(path, data.warnings)
    try:
        backends.append(_SqliteBackend(path))
    except Exception as exc:
        data.warnings.append(f"sqlite fallback unavailable: {type(exc).__name__}: {exc}")
    try:
        for backend in backends:
            try:
                rows = backend.messages(session_id)
                meta = backend.session(session_id) or {}
            except Exception as exc:
                data.warnings.append(f"{backend.name} read failed: {type(exc).__name__}: {exc}")
                continue
            data.rows = [normalize_row(r) for r in rows]
            data.meta = {k: meta.get(k) for k in _SESSION_META_KEYS if k in meta}
            data.backend = backend.name
            break
        if not data.backend:
            data.warnings.append(f"could not read session {session_id!r} from {path}")
    finally:
        for backend in backends:
            backend.close()
    return data


def load_transcript(session_id: str, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return the display transcript (compacted history + compression ancestors) as row dicts.

    Rows carry ``role, content, tool_calls[], tool_call_id, tool_name, timestamp, display_kind,
    display_metadata, _compressed_summary`` and more. Returns ``[]`` if the session can't be read.
    """
    return read_session(session_id, db_path).rows


def list_recent_sessions(limit: int = 20, db_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Most recently active sessions (newest first) with id/source/title/model/timestamps/counts."""
    path = Path(db_path) if db_path else default_db_path()
    try:
        backend = _SqliteBackend(path)
    except Exception:
        return []
    try:
        return backend.recent(limit)
    except Exception:
        return []
    finally:
        backend.close()


def resolve_session_ref(ref: str, db_path: str | Path | None = None,
                        skip_sources: tuple[str, ...] = ("cron",)) -> str | None:
    """``latest`` → newest session not from ``skip_sources``; otherwise an exact id or unique prefix."""
    recent = list_recent_sessions(400, db_path)
    if ref == "latest":
        for s in recent:
            if s.get("source") not in skip_sources:
                return s["id"]
        return None
    ids = [s["id"] for s in recent]
    if ref in ids:
        return ref
    matches = [i for i in ids if i.startswith(ref)]
    if len(matches) == 1:
        return matches[0]
    path = Path(db_path) if db_path else default_db_path()
    try:
        backend = _SqliteBackend(path)
        try:
            found = [r[0] for r in backend._conn.execute(
                "SELECT id FROM sessions WHERE id = ? OR id LIKE ? LIMIT 2", (ref, ref + "%"))]
        finally:
            backend.close()
    except Exception:
        return None
    return found[0] if len(found) == 1 else None
