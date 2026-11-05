"""Transcript rows → :class:`~showreel_core.contracts.Event` list (SPEC 3.1).

Entry point: :func:`extract_events`. Every assistant ``tool_calls[i]`` is paired with the tool row
whose ``tool_call_id`` matches; each Hermes tool has a small handler that pulls verbatim content
out of the arguments and the result. Unknown/MCP tools become ``tool_other``. Extraction never
raises: a handler failure is recorded in ``ExtractResult.warnings`` and a generic event is emitted.

Compaction: Hermes replaces old tool results with one-line stubs (``[terminal] ran `…` -> exit 0``,
``[write_file output demoted at compaction …]``). Arguments survive compaction, so file writes and
patches stay verbatim; such events get ``data.stub = True`` and only what the stub states is
trusted for the result side. Compaction summary messages become ``assistant_note`` stubs.

Media: images are referenced by ``data.src`` (original path) / ``data.url``; :mod:`.assets`
copies them into the job dir later. Inline (base64) images are kept in ``data["_inline_b64"]`` until
assets are collected.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ..contracts import Event
from . import diffparse
from .stats import parse_test_summary
from .textutil import (IMAGE_EXTS, basename, clip, first_comment_or_line, is_local_path, lang_for, norm_path,
                       output_lines, short_path)

MAX_FILE_LINES = 400        # file_write lines kept per event (CODE scenes use <= 18)
MAX_HUNK_LINES = 300        # diff lines kept per file_patch event
MAX_TEXT_CHARS = 4000       # user/assistant text kept per event

_UNTRUSTED_RE = re.compile(r"^\s*<untrusted_tool_result[^>]*>\n?(.*?)(?:</untrusted_tool_result>\s*)?$", re.S)
_STUB_RE = re.compile(r"^\[(\w+)(?: output demoted at compaction[^\]]*)?\]")
_DEMOTED_RE = re.compile(r"^\[(\w+) output demoted at compaction")
_MEDIA_RE = re.compile(r"MEDIA:\s*(\S[^\n]*?)\s*$", re.M)
_IMG_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]{1,2}|/|~[\\/])[^\s\"'<>|*?`]*?\.(?:png|jpe?g|webp|gif)\b", re.I)
_URL_NAV_RE = re.compile(r"\b(?:new_tab|goto_url|goto|navigate|open_url)\(\s*[\"'](https?://[^\"']+)[\"']")
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+")
_EXIT_RE = re.compile(r"->\s*exit\s+(-?\d+)")
_SYSTEM_USER_PREFIXES = (
    "[IMPORTANT:", "[Cron delivery:", "[CONTEXT COMPACTION", "[ASYNC DELEGATION", "[STILL IN PROGRESS",
    "[System:", "[SYSTEM:", "[Your active task list", "[Note:", "[Background process",
)
_STEER_RE = re.compile(r"^\[OUT-OF-BAND USER MESSAGE[^\]]*\]\s*\n?(.*?)\n?\[/OUT-OF-BAND USER MESSAGE\]\s*$", re.S)
_TODO_DONE = {"completed", "done", "cancelled"}


# ----------------------------------------------------------------------------- types

@dataclass
class ToolResult:
    """A decoded tool result."""
    text: str = ""
    json: Any = None
    stub: bool = False
    failed: bool = False
    error: str = ""
    spilled_path: str = ""
    images: list[str] = field(default_factory=list)       # inline base64 image payloads
    missing: bool = False                                 # no tool row at all


@dataclass
class ExtractResult:
    events: list[Event]
    warnings: list[str] = field(default_factory=list)
    unpaired_results: int = 0
    unanswered_calls: int = 0


@dataclass
class _Ctx:
    t0: float
    events: list[Event] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    known: dict[str, list[str] | None] = field(default_factory=dict)  # path key -> last known lines
    last_url: str = ""

    def add(self, kind: str, tool: str, title: str, summary: str, data: dict[str, Any],
            ok: bool = True, ts: float | None = None) -> Event:
        ev = Event(id=f"e{len(self.events)}", t=round(max(0.0, (ts or self.t0) - self.t0), 2), kind=kind,
                   tool=tool, title=clip(title, 80), summary=clip(summary, 160), data=data, ok=bool(ok))
        self.events.append(ev)
        return ev


# ------------------------------------------------------------------------- decoding

def _text_of(content: Any) -> tuple[str, list[str]]:
    """Flatten message content (str or multimodal parts) into text + inline base64 images."""
    if content is None:
        return "", []
    if isinstance(content, str):
        return content, []
    if isinstance(content, dict):
        content = [content]
    texts: list[str] = []
    images: list[str] = []
    if isinstance(content, list):
        for part in content:
            if isinstance(part, str):
                texts.append(part)
            elif isinstance(part, dict):
                ptype = part.get("type")
                if ptype in ("text", "input_text", "output_text"):
                    texts.append(str(part.get("text") or ""))
                elif ptype in ("image_url", "image", "input_image"):
                    url = part.get("image_url")
                    url = url.get("url") if isinstance(url, dict) else url
                    src = part.get("source") if isinstance(part.get("source"), dict) else {}
                    if isinstance(url, str) and url.startswith("data:image/") and ";base64," in url:
                        images.append(url.split(";base64,", 1)[1])
                    elif src.get("type") == "base64" and src.get("data"):
                        images.append(str(src["data"]))
    else:
        texts.append(str(content))
    return "\n".join(t for t in texts if t), images


def _loads(s: str) -> Any:
    s = s.strip()
    if not s or s[0] not in "{[":
        return None
    try:
        return json.loads(s)
    except ValueError:
        return None


def decode_result(row: dict[str, Any] | None, tool_name: str) -> ToolResult:
    """Decode a tool row's content: unwrap untrusted wrappers, detect stubs/spills/failures."""
    if row is None:
        return ToolResult(missing=True)
    text, images = _text_of(row.get("content"))
    res = ToolResult(images=images)
    m = _UNTRUSTED_RE.match(text)
    if m:
        body = m.group(1)
        # drop the fixed preface paragraph ("The following content was retrieved ...")
        if body.startswith("The following content") and "\n\n" in body:
            body = body.split("\n\n", 1)[1]
        text = body.rstrip()
    if text.startswith("<persisted-output>"):
        pm = re.search(r"Full output saved to:\s*(.+)", text)
        res.spilled_path = pm.group(1).strip() if pm else ""
    stub = _STUB_RE.match(text)
    if (stub and len(text) < 700 and (stub.group(1) == tool_name or _DEMOTED_RE.match(text)
                                       or " chars" in text[:400] or "->" in text[:400])) \
            or text.startswith(("[Duplicate tool output", "[screenshot removed")):
        res.stub = True
        if " FAILED" in text[:400]:
            res.failed = True
    res.text = text
    res.json = _loads(text) if not res.stub else None
    if isinstance(res.json, dict):
        err = res.json.get("error")
        if (err and res.json.get("success") is not True) or res.json.get("success") is False \
                or res.json.get("ok") is False:
            res.failed = True
            res.error = clip(str(err or res.json.get("message") or "failed"), 200)
    if text.startswith(("Error executing tool", "Tool call rejected")) or re.match(r"^Tool '[^']+' does not exist", text):
        res.failed, res.error = True, clip(text, 200)
    return res


def _args_of(call: dict[str, Any]) -> dict[str, Any]:
    fn = call.get("function") or {}
    raw = fn.get("arguments", call.get("arguments"))
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            out = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return {"_raw": raw}
        return out if isinstance(out, dict) else {"_raw": raw}
    return {}


def _name_of(call: dict[str, Any]) -> str:
    fn = call.get("function") or {}
    return str(fn.get("name") or call.get("name") or "")


def _image_paths(text: str) -> list[str]:
    """Local image paths mentioned in text (JSON-escaped backslashes normalised), deduped."""
    out: list[str] = []
    for m in _MEDIA_RE.finditer(text or ""):
        p = m.group(1).strip().strip("`'\"")
        if p.lower().endswith(IMAGE_EXTS) and p not in out:
            out.append(p)
    for m in _IMG_PATH_RE.finditer((text or "").replace("\\\\", "\\")):
        p = m.group(0).rstrip(".,;:)")
        if p.startswith("//") or p in out:
            continue
        out.append(p)
    return out


_SAVE_LINE_RE = re.compile(r"(?i)\b(?:saved|wrote|written|writing|created|exported|rendered|generated|output|"
                           r"done|built|encoded|muxed)\b|->|→")
_DELIVERABLE_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]{1,2}|~[\\/])?[\w.\-\\/]*?[\w\-]+\.(?:html?|png|jpe?g|webp|gif|svg|mp4|webm|mov|mkv|"
    r"mp3|wav|ogg|m4a|flac|pdf|pptx|docx|xlsx|csv|ipynb|zip)\b", re.I)
KEY_FILE_NAMES = {"package.json", "pyproject.toml", "cargo.toml", "setup.py", "setup.cfg", "go.mod", "readme.md",
                  "readme.rst", "readme.txt", "readme", "plugin.yaml", "index.html", "manifest.json", "app.json"}


def output_refs(text: str) -> dict[str, list[str]]:
    """URLs and 'saved file' paths mentioned anywhere in a (full, untruncated) tool output."""
    urls = list(dict.fromkeys(u.rstrip(".,;:'\")]") for u in _URL_RE.findall(text or "")))[:12]
    saved: list[str] = []
    for line in (text or "").replace("\\\\", "\\").splitlines():
        if len(saved) >= 10:
            break
        if not _SAVE_LINE_RE.search(line):
            continue
        for m in _DELIVERABLE_PATH_RE.finditer(line):
            path = m.group(0).strip().strip("'\"`")
            if "://" in path or len(path) < 5:
                continue
            if path not in saved:
                saved.append(path)
    return {"urls": urls, "saved_paths": saved}


def _media_refs(text: str) -> list[str]:
    return [m.group(1).strip().strip("`'\"") for m in _MEDIA_RE.finditer(text or "")]


# ----------------------------------------------------------------------- tool handlers

Handler = Callable[[_Ctx, str, dict[str, Any], ToolResult, float | None, float | None], None]


def _stub_note(res: ToolResult) -> dict[str, Any]:
    return {"stub": True, "stub_text": clip(res.text, 300)} if res.stub else {}


def _h_terminal(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                elapsed: float | None) -> None:
    cmd = str(args.get("command") or args.get("cmd") or "")
    j = res.json if isinstance(res.json, dict) else {}
    out_text = str(j.get("output") or "") if j else ("" if res.stub else res.text)
    if j and not out_text and j.get("error"):
        out_text = str(j["error"])
    lines, total, gap = output_lines(out_text)
    exit_code = j.get("exit_code") if j else None
    if exit_code is None and res.stub:
        m = _EXIT_RE.search(res.text)
        exit_code = int(m.group(1)) if m else None
    if isinstance(exit_code, str) and exit_code.lstrip("-").isdigit():
        exit_code = int(exit_code)
    background = bool(args.get("background")) or bool(j.get("pid") and j.get("session_id"))
    tests = parse_test_summary(out_text)
    ok = not res.failed and (exit_code in (0, None)) and not (tests and tests.get("failed"))
    if background and exit_code is None:
        ok = not res.failed
    data: dict[str, Any] = {"cmd": cmd, "output_lines": lines, "output_total": total, "output_gap": gap,
                            "exit_code": exit_code if isinstance(exit_code, int) else None,
                            "elapsed_s": elapsed, "background": background, **_stub_note(res)}
    if tests:
        data["tests"] = tests
    data.update(output_refs(out_text))
    if args.get("workdir"):
        data["cwd"] = str(args["workdir"])
    first = cmd.strip().splitlines()[0] if cmd.strip() else ""
    title = re.sub(r"^(?:cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s*&&\s*)+", "", first) or first
    summ = f"$ {title}"
    if tests:
        summ += f" → {tests['passed']} passed" + (f", {tests['failed']} failed" if tests.get("failed") else "")
    elif exit_code is not None:
        summ += f" → exit {exit_code}"
    elif background:
        summ += " → started in background"
    ctx.add("terminal", tool, title, summ, data, ok, ts)


def _h_execute_code(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                    elapsed: float | None) -> None:
    code = str(args.get("code") or "")
    j = res.json if isinstance(res.json, dict) else {}
    out_text = str(j.get("output") or "") if j else ("" if res.stub else res.text)
    if j.get("error") and not out_text:
        out_text = str(j["error"])
    lines, total, gap = output_lines(out_text)
    code_lines, code_total, _ = output_lines(code, max_lines=40, head=40)
    label, first = first_comment_or_line(code)
    exit_code = j.get("exit_code") if isinstance(j.get("exit_code"), int) else None
    tests = parse_test_summary(out_text)
    ok = not res.failed and exit_code in (0, None) and j.get("status", "success") in ("success", "ok", None)
    data: dict[str, Any] = {"cmd": first, "shell": "python", "code_lines": code_lines, "code_total": code_total,
                            "output_lines": lines, "output_total": total, "output_gap": gap,
                            "exit_code": exit_code, "elapsed_s": j.get("duration_seconds", elapsed),
                            "label": label, **_stub_note(res)}
    if tests:
        data["tests"] = tests
    data.update(output_refs(out_text))
    title = label or first or "python"
    ctx.add("terminal", tool, title, f"python · {title}", data, ok, ts)


def _h_process(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
               elapsed: float | None) -> None:
    j = res.json if isinstance(res.json, dict) else {}
    action = str(args.get("action") or "")
    if j.get("command") and j.get("status") in ("exited", "completed", "killed", "finished") \
            and action in ("wait", "poll", "log", "status", ""):
        lines, total, gap = output_lines(str(j.get("output") or j.get("output_preview") or ""))
        exit_code = j.get("exit_code") if isinstance(j.get("exit_code"), int) else None
        tests = parse_test_summary(str(j.get("output") or ""))
        data = {"cmd": str(j["command"]), "output_lines": lines, "output_total": total, "output_gap": gap,
                "exit_code": exit_code, "elapsed_s": j.get("uptime_seconds"), "background": True,
                "completion": True}
        if tests:
            data["tests"] = tests
        data.update(output_refs(str(j.get("output") or "")))
        ok = exit_code in (0, None) and not (tests and tests.get("failed"))
        first = str(j["command"]).strip().splitlines()[0]
        ctx.add("terminal", tool, first, f"background $ {first} → exit {exit_code}", data, ok, ts)
        return
    _h_generic(ctx, tool, args, res, ts, elapsed)


def _path_key(path: str) -> str:
    return norm_path(path)


def _h_write_file(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                  elapsed: float | None) -> None:
    path = str(args.get("path") or args.get("file_path") or "")
    content = str(args.get("content") or "")
    all_lines = content.replace("\r\n", "\n").split("\n")
    if all_lines and all_lines[-1] == "" and len(all_lines) > 1:
        all_lines.pop()
    key = _path_key(path)
    prev_known = key in ctx.known
    prev = ctx.known.get(key)
    new_file = not prev_known
    j = res.json if isinstance(res.json, dict) else {}
    if isinstance(j.get("created"), bool):
        new_file = j["created"]
    ok = not res.failed and not j.get("stale_write_blocked")
    adds = dels = None
    if new_file:
        adds, dels = len(all_lines), 0
    elif prev is not None:
        fp = diffparse.synth_replace(path, "\n".join(prev), "\n".join(all_lines), context=0)[0]
        adds, dels = fp["adds"], fp["dels"]
    if ok:
        ctx.known[key] = all_lines
    data = {"path": path, "path_key": key, "lang": lang_for(path), "lines": all_lines[:MAX_FILE_LINES],
            "total_lines": len(all_lines), "new_file": new_file, "adds": adds, "dels": dels, **_stub_note(res)}
    if res.failed:
        data["error"] = res.error
    verb = "created" if new_file else "rewrote"
    ctx.add("file_write", tool, short_path(path), f"{verb} {short_path(path)} ({len(all_lines)} lines)", data, ok, ts)


def _emit_patch_files(ctx: _Ctx, tool: str, files: list[dict[str, Any]], res: ToolResult, ts: float | None,
                      synthetic: bool, fallback_path: str = "") -> None:
    for fp in files:
        path = fp.get("path") or fallback_path
        if fallback_path and len(files) == 1:
            path = fallback_path       # the args spelling, not the diff's a/ b/ form
        key = _path_key(path)
        new_file = fp.get("action") == "add" and key not in ctx.known
        hunks, kept = [], 0
        for h in fp["hunks"]:
            if kept >= MAX_HUNK_LINES:
                break
            lines = h["lines"][: MAX_HUNK_LINES - kept]
            kept += len(lines)
            hunks.append({"header": h["header"], "lines": lines})
        data = {"path": path, "path_key": key, "lang": lang_for(path), "hunks": hunks, "adds": fp["adds"],
                "dels": fp["dels"], "action": fp.get("action", "update"), "synthetic": synthetic,
                "new_file": new_file, **_stub_note(res)}
        if fp.get("move_to"):
            data["move_to"] = fp["move_to"]
        if res.failed:
            data["error"] = res.error
        if not res.failed:
            ctx.known.setdefault(key, None)
            if ctx.known.get(key) is not None:
                ctx.known[key] = None      # content changed; we no longer know it line-for-line
        ok = not res.failed
        ctx.add("file_patch", tool, short_path(path), f"+{fp['adds']} −{fp['dels']} in {short_path(path)}",
                data, ok, ts)


def _h_patch(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
             elapsed: float | None) -> None:
    path = str(args.get("path") or "")
    j = res.json if isinstance(res.json, dict) else {}
    diff = j.get("diff") if isinstance(j.get("diff"), str) else ""
    files: list[dict[str, Any]] = []
    synthetic = False
    if diff:
        files = diffparse.parse_unified(diff)
    if not files and isinstance(args.get("patch"), str) and "*** " in args["patch"]:
        files = diffparse.parse_v4a(args["patch"])
        path = "" if len(files) != 1 else (files[0]["path"] or path)
    if not files and ("old_string" in args or "new_string" in args):
        files = diffparse.synth_replace(path, str(args.get("old_string") or ""), str(args.get("new_string") or ""))
        synthetic = True
    if not files:
        ctx.add("file_patch", tool, short_path(path) or "patch", f"patch {short_path(path)}",
                {"path": path, "path_key": _path_key(path), "lang": lang_for(path), "hunks": [], "adds": 0,
                 "dels": 0, **_stub_note(res)}, not res.failed, ts)
        return
    _emit_patch_files(ctx, tool, files, res, ts, synthetic, fallback_path=path if len(files) == 1 else "")


def _h_read_file(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                 elapsed: float | None) -> None:
    path = str(args.get("path") or "")
    key = _path_key(path)
    j = res.json if isinstance(res.json, dict) else {}
    total = j.get("total_lines")
    offset = int(args.get("offset") or 1) if str(args.get("offset") or "1").isdigit() else 1
    if isinstance(j.get("content"), str) and offset <= 1 and not j.get("truncated") and not res.failed:
        lines = [re.sub(r"^\s*\d+\|", "", l) for l in j["content"].split("\n")]
        if lines and lines[-1] == "":
            lines.pop()
        if total is None or len(lines) >= int(total):
            ctx.known[key] = lines
        else:
            ctx.known.setdefault(key, None)
    elif not res.failed and not j.get("not_found"):
        ctx.known.setdefault(key, None)
    data = {"path": path, "path_key": key, "lang": lang_for(path), "offset": offset,
            "total_lines": total, **_stub_note(res)}
    if basename(path).lower() in KEY_FILE_NAMES and isinstance(j.get("content"), str):
        data["content_lines"] = [re.sub(r"^\s*\d+\|", "", l) for l in j["content"].split("\n")][:MAX_FILE_LINES]
    ctx.add("file_read", tool, short_path(path), f"read {short_path(path)}", data,
            not res.failed and not j.get("not_found"), ts)


def _h_search_files(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                    elapsed: float | None) -> None:
    j = res.json if isinstance(res.json, dict) else {}
    pattern = str(args.get("pattern") or "")
    data = {"action": "search", "pattern": pattern, "path": str(args.get("path") or "."),
            "target": str(args.get("target") or "content"), "count": j.get("total_count"), **_stub_note(res)}
    ctx.add("tool_other", tool, f"search '{pattern}'", f"searched {data['target']} for '{pattern}'"
            + (f" → {data['count']} matches" if data["count"] is not None else ""), data, not res.failed, ts)


def _screenshot(ctx: _Ctx, tool: str, src: str, ts: float | None, *, url: str = "", source: str = "",
                extra: dict[str, Any] | None = None, inline: str = "", ok: bool = True) -> Event:
    data: dict[str, Any] = {"src": src, "src_key": norm_path(src) if src else "", "url": url or "",
                            "source": source or tool, "path": "", "w": None, "h": None, **(extra or {})}
    if inline:
        data["_inline_b64"] = inline
    label = short_path(src, 2) if src else (url or "inline image")
    return ctx.add("screenshot", tool, label, f"screenshot · {label}", data, ok, ts)


def _h_browser_exec(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                    elapsed: float | None) -> None:
    code = str(args.get("code") or "")
    label, first = first_comment_or_line(code)
    urls = list(dict.fromkeys(_URL_NAV_RE.findall(code)))
    j = res.json if isinstance(res.json, dict) else {}
    out = str(j.get("output") or "") if j else res.text
    if urls:
        ctx.last_url = urls[-1]
        ctx.add("browser_nav", tool, label or urls[0], f"opened {urls[0]}" + (f" (+{len(urls) - 1})" if len(urls) > 1 else ""),
                {"url": urls[0], "urls": urls, "label": label, **_stub_note(res)}, not res.failed, ts)
    shots = _image_paths(out)
    for p in shots:
        _screenshot(ctx, tool, p, ts, url=ctx.last_url, source="browser")
    for b64 in res.images:
        _screenshot(ctx, tool, "", ts, url=ctx.last_url, source="browser", inline=b64)
    if not urls and not shots and not res.images:
        lines, total, gap = output_lines(out, max_lines=12, head=6)
        ctx.add("tool_other", tool, label or first or "browser", f"browser · {label or first}",
                {"action": "browser", "label": label, "output_lines": lines, **_stub_note(res)}, not res.failed, ts)


def _h_browser_legacy(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                      elapsed: float | None) -> None:
    """browser_navigate/click/snapshot/vision/... (older Hermes and MCP browser servers)."""
    j = res.json if isinstance(res.json, dict) else {}
    action = tool.split("browser_", 1)[-1] if "browser_" in tool else tool
    url = str(args.get("url") or j.get("url") or "")
    if url and ("navigate" in action or "open" in action or "goto" in action):
        ctx.last_url = url
        ctx.add("browser_nav", tool, url, f"opened {url}", {"url": url, "urls": [url], "title": str(j.get("title") or ""),
                                                            **_stub_note(res)}, not res.failed, ts)
    paths = [str(j[k]) for k in ("screenshot_path", "image_path", "path", "file_path") if isinstance(j.get(k), str)
             and j[k].lower().endswith(IMAGE_EXTS)] + _image_paths(res.text)
    paths = list(dict.fromkeys(paths))
    for p in paths:
        _screenshot(ctx, tool, p, ts, url=ctx.last_url, source="browser")
    for b64 in res.images:
        _screenshot(ctx, tool, "", ts, url=ctx.last_url, source="browser", inline=b64)
    if not paths and not res.images and not (url and "navigate" in action):
        ctx.add("tool_other", tool, f"browser {action}", f"browser {action}" + (f" {url}" if url else ""),
                {"action": f"browser_{action}", **_stub_note(res)}, not res.failed, ts)


def _h_vision(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
              elapsed: float | None) -> None:
    src = str(args.get("image_url") or args.get("image") or args.get("path") or "")
    question = clip(str(args.get("question") or ""), 200)
    if src and is_local_path(src):
        _screenshot(ctx, tool, src, ts, source="vision_analyze", extra={"question": question}, ok=not res.failed)
    else:
        ctx.add("tool_other", tool, "vision", f"looked at {clip(src, 60) or 'an image'}",
                {"action": "vision", "url": src if src.startswith("http") else "", "question": question},
                not res.failed, ts)


def _h_computer_use(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                    elapsed: float | None) -> None:
    action = str(args.get("action") or "")
    paths = _image_paths(res.text)
    for p in paths:
        _screenshot(ctx, tool, p, ts, source="desktop", extra={"action": action})
    for b64 in res.images:
        _screenshot(ctx, tool, "", ts, source="desktop", extra={"action": action}, inline=b64)
    if not paths and not res.images:
        detail = args.get("app") or args.get("keys") or args.get("text") or ""
        ctx.add("tool_other", tool, f"desktop {action}", clip(f"desktop {action} {detail}", 160),
                {"action": f"desktop_{action}", **_stub_note(res)}, not res.failed, ts)


def _h_web_search(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                  elapsed: float | None) -> None:
    query = str(args.get("query") or args.get("q") or "")
    j = res.json if isinstance(res.json, dict) else {}
    web = ((j.get("data") or {}).get("web") if isinstance(j.get("data"), dict) else None) or j.get("results") or []
    web = [w for w in web if isinstance(w, dict)] if isinstance(web, list) else []
    data = {"query": query, "titles": [clip(str(w.get("title") or ""), 100) for w in web[:5]],
            "urls": [str(w.get("url") or "") for w in web[:5]], "count": len(web), **_stub_note(res)}
    ctx.add("web_search", tool, query, f"searched the web: {query}", data, not res.failed, ts)


def _h_web_extract(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                   elapsed: float | None) -> None:
    urls = args.get("urls") or ([args["url"]] if args.get("url") else [])
    urls = [u.get("url", "") if isinstance(u, dict) else str(u) for u in (urls if isinstance(urls, list) else [urls])]
    j = res.json if isinstance(res.json, dict) else {}
    results = j.get("results") if isinstance(j.get("results"), list) else []
    titles = [clip(str(r.get("title") or ""), 100) for r in results if isinstance(r, dict)][:5]
    first = urls[0] if urls else ""
    ctx.add("web_extract", tool, first, f"read {first}" + (f" (+{len(urls) - 1} more)" if len(urls) > 1 else ""),
            {"url": first, "urls": urls, "titles": titles, **_stub_note(res)}, not res.failed, ts)


def _h_image_generate(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                      elapsed: float | None) -> None:
    j = res.json if isinstance(res.json, dict) else {}
    img = j.get("image") or j.get("path") or j.get("file_path") or ""
    if isinstance(img, list):
        img = img[0] if img else ""
    if isinstance(img, dict):
        img = img.get("url") or img.get("path") or ""
    img = str(img or "")
    media = [m for m in _media_refs(res.text) if m.lower().endswith(IMAGE_EXTS)]
    src = img if img and is_local_path(img) else (media[0] if media else "")
    url = img if img.startswith("http") else ""
    prompt = clip(str(args.get("prompt") or ""), 300)
    data = {"src": src, "src_key": norm_path(src) if src else "", "url": url, "prompt": prompt, "path": "",
            "w": None, "h": None, "source": "image_generate", **_stub_note(res)}
    if res.images:
        data["_inline_b64"] = res.images[0]
    ctx.add("image_generated", tool, clip(prompt, 60) or "image", f"generated an image: {clip(prompt, 100)}",
            data, not res.failed and bool(src or url or res.images), ts)


def _h_tts(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
           elapsed: float | None) -> None:
    j = res.json if isinstance(res.json, dict) else {}
    text = clip(str(args.get("text") or ""), 300)
    ctx.add("tool_other", tool, "voice-over", f"spoke: {clip(text, 100)}",
            {"action": "tts", "text": text, "audio": str(j.get("file_path") or ""), **_stub_note(res)},
            not res.failed, ts)


def _h_delegate(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
                elapsed: float | None) -> None:
    tasks = args.get("tasks")
    goals: list[str] = []
    if isinstance(tasks, list):
        goals = [str(t.get("goal") or "") for t in tasks if isinstance(t, dict)]
    elif args.get("goal"):
        goals = [str(args["goal"])]
    j = res.json if isinstance(res.json, dict) else {}
    if not goals and isinstance(j.get("goals"), list):
        goals = [str(g) for g in j["goals"]]
    if not goals:
        action = str(args.get("action") or "manage")
        ctx.add("tool_other", tool, f"subagent {action}", f"subagent {action}", {"action": f"delegate_{action}"},
                not res.failed, ts)
        return
    goals = [clip(g, 300) for g in goals]
    ctx.add("delegate", tool, clip(goals[0], 80), f"delegated {len(goals)} task(s): {clip(goals[0], 100)}",
            {"goals": goals, "count": len(goals), "mode": str(j.get("mode") or ""), **_stub_note(res)},
            not res.failed, ts)


def _h_todo(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
            elapsed: float | None) -> None:
    j = res.json if isinstance(res.json, dict) else {}
    raw = j.get("todos") if isinstance(j.get("todos"), list) else args.get("todos")
    items = [{"text": clip(str(t.get("content") or t.get("text") or ""), 200), "status": str(t.get("status") or "pending")}
             for t in (raw if isinstance(raw, list) else []) if isinstance(t, dict)]
    if not items:
        ctx.add("tool_other", tool, "todo", "updated the task list", {"action": "todo", **_stub_note(res)}, not res.failed, ts)
        return
    done = sum(1 for i in items if i["status"] in _TODO_DONE)
    ctx.add("todo", tool, f"plan · {len(items)} items", f"task list: {done}/{len(items)} done",
            {"items": items, "done": done, **_stub_note(res)}, not res.failed, ts)


def _h_skill(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
             elapsed: float | None) -> None:
    if tool == "skill_manage":
        ops = args.get("operations") if isinstance(args.get("operations"), list) else [args]
        pairs = [(str(o.get("action") or ""), str(o.get("name") or "")) for o in ops if isinstance(o, dict)]
        names = list(dict.fromkeys(n for _, n in pairs if n))
        actions = list(dict.fromkeys(a for a, _ in pairs if a))
        ctx.add("skill", tool, ", ".join(names) or "skills", f"{'/'.join(actions) or 'updated'} skill {', '.join(names)}",
                {"action": "/".join(actions), "names": names, **_stub_note(res)}, not res.failed, ts)
    elif tool == "skills_list":
        ctx.add("skill", tool, "skills", "listed skills", {"action": "list", "names": []}, not res.failed, ts)
    else:
        name = str(args.get("name") or "")
        ctx.add("skill", tool, name or "skill", f"loaded skill {name}", {"action": "view", "names": [name],
                "file": str(args.get("file_path") or "")}, not res.failed, ts)


def _h_clarify(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
               elapsed: float | None) -> None:
    qs = args.get("questions") if isinstance(args.get("questions"), list) else ([args.get("question")] if args.get("question") else [])
    questions = [clip(str(q.get("question") if isinstance(q, dict) else q), 200) for q in qs if q]
    j = res.json if isinstance(res.json, dict) else {}
    answers: list[str] = []
    for r in j.get("responses") or []:
        if isinstance(r, dict):
            val = r.get("answer") or r.get("response") or r.get("user_response") or r.get("selected")
            answers.append(clip(json.dumps(val, ensure_ascii=False) if isinstance(val, (list, dict)) else str(val or ""), 200))
        else:
            answers.append(clip(str(r), 200))
    ctx.add("clarify", tool, clip(questions[0] if questions else "question", 80),
            f"asked the user: {clip(questions[0], 120) if questions else ''}",
            {"questions": questions, "answers": answers, **_stub_note(res)}, not res.failed, ts)


def _h_generic(ctx: _Ctx, tool: str, args: dict[str, Any], res: ToolResult, ts: float | None,
               elapsed: float | None) -> None:
    preview = []
    for k, v in list(args.items())[:3]:
        if k.startswith("_"):
            continue
        sval = json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)
        preview.append(f"{k}={clip(sval, 60)}")
    data: dict[str, Any] = {"action": tool, "args_preview": preview, **_stub_note(res)}
    if tool.startswith("mcp_") or "__" in tool:
        parts = tool[4:].split("_", 1) if tool.startswith("mcp_") else tool.split("__", 1)
        data["mcp_server"], data["mcp_tool"] = (parts + [""])[:2]
    if tool == "browser_vault":       # never surface anything from the credential vault
        data["args_preview"] = []
    ctx.add("tool_other", tool, tool, clip(f"{tool} {' '.join(preview)}", 160), data, not res.failed, ts)
    paths = _image_paths(res.text) if tool != "browser_vault" else []
    for p in paths[:4]:
        _screenshot(ctx, tool, p, ts, source=tool)


_HANDLERS: dict[str, Handler] = {
    "terminal": _h_terminal, "execute_code": _h_execute_code, "process_manage": _h_process,
    "process": _h_process, "write_file": _h_write_file, "patch": _h_patch, "read_file": _h_read_file,
    "search_files": _h_search_files, "browser_exec": _h_browser_exec, "vision_analyze": _h_vision,
    "computer_use": _h_computer_use, "web_search": _h_web_search, "x_search": _h_web_search,
    "web_extract": _h_web_extract, "image_generate": _h_image_generate, "text_to_speech": _h_tts,
    "delegate_task": _h_delegate, "todo": _h_todo, "todo_list": _h_todo, "skill_view": _h_skill,
    "skill_manage": _h_skill, "skills_list": _h_skill, "clarify": _h_clarify,
}


def _handler_for(tool: str) -> Handler:
    if tool in _HANDLERS:
        return _HANDLERS[tool]
    low = tool.lower()
    if "browser" in low or low.endswith(("_navigate", "_screenshot", "_take_screenshot")):
        return _h_browser_legacy
    return _h_generic


# --------------------------------------------------------------------- message rows

def _user_text(row: dict[str, Any]) -> str:
    meta = row.get("display_metadata") or {}
    text, _ = _text_of(row.get("content"))
    shown = meta.get("display_text") if isinstance(meta, dict) else None
    if isinstance(shown, str) and shown.strip() and not shown.startswith(("Background Process", "Subagent Tasks")):
        return shown
    return text


def _process_complete(ctx: _Ctx, text: str, ts: float | None) -> None:
    m_exit = re.search(r"exit code (-?\d+)", text[:400])
    m_cmd = re.search(r"^Command:\s*(.+)$", text, re.M)
    out = text.split("\nOutput:\n", 1)[1] if "\nOutput:\n" in text else ""
    out = re.split(r"\n\[(?:Use |Note|IMPORTANT)", out)[0]
    lines, total, gap = output_lines(out)
    exit_code = int(m_exit.group(1)) if m_exit else None
    tests = parse_test_summary(out)
    cmd = m_cmd.group(1).strip() if m_cmd else ""
    data = {"cmd": cmd, "output_lines": lines, "output_total": total, "output_gap": gap, "exit_code": exit_code,
            "elapsed_s": None, "background": True, "completion": True, "notification": True}
    if tests:
        data["tests"] = tests
    data.update(output_refs(out))
    ctx.add("terminal", "process_complete", cmd or "background process", f"background $ {clip(cmd, 100)} → exit {exit_code}",
            data, exit_code in (0, None) and not (tests and tests.get("failed")), ts)


def _delegation_complete(ctx: _Ctx, text: str, ts: float | None) -> None:
    tasks = re.findall(r"^--- ([✓✗✔✘×!?]) TASK (\d+)/(\d+): (.+)$", text, re.M)
    ok_n = sum(1 for t in tasks if t[0] in "✓✔")
    goals = [clip(t[3], 200) for t in tasks]
    ctx.add("delegate", "delegate_task", f"{len(tasks)} subagent(s) finished", f"{ok_n}/{len(tasks)} subagent task(s) finished",
            {"goals": goals, "count": len(tasks), "completed": True, "succeeded": ok_n, "notification": True},
            ok_n == len(tasks), ts)


def _is_system_user(text: str) -> bool:
    return text.lstrip().startswith(_SYSTEM_USER_PREFIXES)


def _handle_user(ctx: _Ctx, row: dict[str, Any], ts: float | None, pending_cron: list[str]) -> None:
    kind = row.get("display_kind")
    raw, _ = _text_of(row.get("content"))
    if row.get("_compressed_summary") or raw.startswith("[CONTEXT COMPACTION"):
        ctx.add("assistant_note", "", "context compacted", f"earlier context compacted ({len(raw):,} chars summary)",
                {"stub": True, "compaction": True, "text": ""}, True, ts)
        return
    if kind == "process_complete" or raw.startswith("[IMPORTANT: Background process"):
        _process_complete(ctx, raw, ts)
        return
    if kind == "async_delegation_complete" or raw.startswith("[ASYNC DELEGATION"):
        _delegation_complete(ctx, raw, ts)
        return
    if kind == "steer":
        m = _STEER_RE.match(raw.strip())
        text = (m.group(1) if m else raw).strip()
        if text.startswith("[STILL IN PROGRESS"):
            return
        ctx.add("user_prompt", "", clip(text, 80), clip(text, 160), {"text": text[:MAX_TEXT_CHARS], "steer": True}, True, ts)
        return
    if kind in ("internal_notification", "hidden"):
        return
    text = _user_text(row)
    if _is_system_user(text):
        if text.startswith("[IMPORTANT: You are running"):
            pending_cron.append(text)
        return
    if not text.strip():
        return
    ctx.add("user_prompt", "", clip(text, 80), clip(text, 160), {"text": text[:MAX_TEXT_CHARS],
            "chars": len(text)}, True, ts)


def _handle_assistant_text(ctx: _Ctx, row: dict[str, Any], ts: float | None, has_calls: bool) -> None:
    text, _ = _text_of(row.get("content"))
    text = text.strip()
    if not text:
        return
    media = _media_refs(text)
    data: dict[str, Any] = {"text": text[:MAX_TEXT_CHARS], "chars": len(text), "turn_end": not has_calls}
    if media:
        data["media"] = media
    ok = row.get("display_kind") != "failed_turn"
    ev = ctx.add("assistant_note", "", clip(text, 80), clip(text, 160), data, ok, ts)
    for p in media:
        if p.lower().endswith(IMAGE_EXTS):
            _screenshot(ctx, "", p, ts, source="deliverable", extra={"artifact": True, "note": ev.id})


# ------------------------------------------------------------------------- main pass

def _unwrap_tool_call(args: dict[str, Any], res: ToolResult) -> list[tuple[str, dict[str, Any], ToolResult]]:
    calls = args.get("calls")
    if isinstance(calls, str):
        try:
            calls = json.loads(calls)
        except ValueError:
            calls = []
    calls = [c for c in calls if isinstance(c, dict)] if isinstance(calls, list) else []
    if not calls:
        return [("tool_call", args, res)]
    out = []
    per: list[Any] | None = None
    if len(calls) > 1:
        j = res.json
        if isinstance(j, dict) and isinstance(j.get("results"), list):
            j = j["results"]
        per = j if isinstance(j, list) and len(j) == len(calls) else None
    for i, c in enumerate(calls):
        inner_args = c.get("arguments")
        if isinstance(inner_args, str):
            try:
                inner_args = json.loads(inner_args)
            except ValueError:
                inner_args = {"_raw": inner_args}
        inner_args = inner_args if isinstance(inner_args, dict) else {}
        if len(calls) == 1:
            inner_res = res
        elif per is not None:
            item = per[i]
            text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            inner_res = decode_result({"content": text}, str(c.get("name") or ""))
        else:
            inner_res = ToolResult(text="", stub=res.stub, failed=res.failed)
        out.append((str(c.get("name") or "tool_call"), inner_args, inner_res))
    return out


def _single_elapsed(call_ts: float | None, res_row: dict[str, Any] | None, n_calls: int) -> float | None:
    if n_calls != 1 or call_ts is None or not res_row or res_row.get("timestamp") is None:
        return None
    dt = float(res_row["timestamp"]) - call_ts
    return round(dt, 1) if 0 <= dt < 86400 else None


def extract_events(rows: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> ExtractResult:
    """Turn transcript rows (see :func:`reader.load_transcript`) into weighted events.

    Never raises. Events are in transcript order with ids ``e0..eN``; ``t`` is seconds since the
    first timestamped row.
    """
    from .weights import assign_weights  # local import keeps the module graph acyclic

    stamps = [float(r["timestamp"]) for r in rows if isinstance(r.get("timestamp"), (int, float))]
    t0 = min(stamps) if stamps else float((meta or {}).get("started_at") or 0.0)
    ctx = _Ctx(t0=t0)
    results: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("role") == "tool" and r.get("tool_call_id"):
            results.setdefault(str(r["tool_call_id"]), r)
    call_ids = {str(c.get("id") or c.get("call_id") or "") for r in rows if r.get("role") == "assistant"
                for c in (r.get("tool_calls") or []) if isinstance(c, dict)}
    used: set[str] = set()
    pending_cron: list[str] = []
    unanswered = 0
    last_ts: float | None = t0
    for idx, row in enumerate(rows):
        ts = row.get("timestamp") if isinstance(row.get("timestamp"), (int, float)) else last_ts
        last_ts = ts
        role = row.get("role")
        try:
            if role == "user":
                _handle_user(ctx, row, ts, pending_cron)
            elif role == "assistant":
                if row.get("display_kind") == "hidden":
                    continue
                calls = [c for c in (row.get("tool_calls") or []) if isinstance(c, dict)]
                _handle_assistant_text(ctx, row, ts, bool(calls))
                for call in calls:
                    cid = str(call.get("id") or call.get("call_id") or "")
                    res_row = results.get(cid)
                    if res_row is None:
                        unanswered += 1
                    else:
                        used.add(cid)
                    name = _name_of(call)
                    args = _args_of(call)
                    res = decode_result(res_row, name)
                    elapsed = _single_elapsed(ts, res_row, len(calls))
                    triples = _unwrap_tool_call(args, res) if name == "tool_call" else [(name, args, res)]
                    for tool, targs, tres in triples:
                        try:
                            _handler_for(tool)(ctx, tool, targs, tres, ts, elapsed)
                        except Exception as exc:  # pragma: no cover - defensive
                            ctx.warnings.append(f"row {row.get('id', idx)} {tool}: {type(exc).__name__}: {exc}")
                            _h_generic(ctx, tool, {}, ToolResult(), ts, elapsed)
            elif role == "tool":
                cid = str(row.get("tool_call_id") or "")
                if cid and cid not in used and results.get(cid) is row and cid not in call_ids:
                    tool = str(row.get("tool_name") or "tool")
                    ev = ctx.add("tool_other", tool, tool, f"{tool} (call not in transcript)",
                                 {"action": tool, "stub_only": True, "stub": True}, True, ts)
                    ev.data["orphan"] = True
        except Exception as exc:  # pragma: no cover - defensive
            ctx.warnings.append(f"row {row.get('id', idx)} ({role}): {type(exc).__name__}: {exc}")
    if not any(e.kind == "user_prompt" for e in ctx.events) and pending_cron:
        text = pending_cron[0]
        ev = Event(id="", t=0.0, kind="user_prompt", tool="", title=clip(text, 80), summary=clip(text, 160),
                   data={"text": text[:MAX_TEXT_CHARS], "synthetic": True})
        ctx.events.insert(0, ev)
        for i, e in enumerate(ctx.events):
            e.id = f"e{i}"
    _mark_final_answer(ctx.events)
    _mark_fixes(ctx.events)
    assign_weights(ctx.events)
    orphans = sum(1 for e in ctx.events if e.data.get("orphan"))
    return ExtractResult(events=ctx.events, warnings=ctx.warnings, unpaired_results=orphans,
                         unanswered_calls=unanswered)


def _mark_final_answer(events: list[Event]) -> None:
    for ev in reversed(events):
        if ev.kind == "assistant_note" and ev.data.get("turn_end") and ev.ok and not ev.data.get("stub"):
            ev.kind = "final_answer"
            return


def _family(cmd: str) -> str:
    """Command family for fail→fix matching: strip ``cd … &&`` and env prefixes, keep 2 tokens."""
    c = cmd.strip().splitlines()[0] if cmd.strip() else ""
    c = re.sub(r"^(?:cd\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s*(?:&&|;)\s*)+", "", c)
    c = re.sub(r"^(?:[A-Z_][A-Z0-9_]*=\S+\s+)+", "", c)
    toks = c.split()
    return " ".join(toks[:2])


def _mark_fixes(events: list[Event]) -> None:
    """Flag the first success after a failure of the same command family (and green-after-red tests)."""
    failed_fams: set[str] = set()
    red_tests = False
    for ev in events:
        if ev.kind != "terminal" or (ev.data.get("stub") and ev.data.get("exit_code") is None):
            continue
        fam = _family(str(ev.data.get("cmd") or ""))
        tests = ev.data.get("tests")
        if tests:
            if tests.get("failed"):
                red_tests = True
            elif red_tests and tests.get("passed"):
                ev.data["fixed"] = True
                ev.data["tests_green_after_red"] = True
                red_tests = False
        if not fam or (ev.data.get("background") and ev.data.get("exit_code") is None):
            continue
        if not ev.ok:
            failed_fams.add(fam)
        elif fam in failed_fams:
            ev.data["fixed"] = True
            failed_fams.discard(fam)
