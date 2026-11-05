"""Model access for the Director: one call signature, a Hermes ``ctx.llm`` adapter, a dev CLI adapter,
and a ledger that persists every call, counts tokens/cost and enforces the call budget and cancellation.

Call signature (:class:`DirectorLlm`)::

    llm(purpose="treatment", instructions=..., text=..., images=[Image(...)], json_schema={...} | None,
        schema_name="showreel.treatment", temperature=0.7, max_tokens=6000, timeout=240) -> LlmReply

``json_schema=None`` asks for free text (scene code). Adapters never raise; errors come back in
``LlmReply.error``. :class:`CallLedger` raises :class:`BudgetExceeded` / :class:`Cancelled` *before* a call.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..story.schema import parse_json_text


@dataclass
class Image:
    """An image input (contact sheet, product thumbnail)."""
    data: bytes
    mime_type: str = "image/png"
    path: str = ""                 # on-disk copy, used by adapters that attach by path
    label: str = ""


@dataclass
class LlmReply:
    """What one model call returned."""
    text: str = ""
    parsed: Any = None
    error: str = ""
    model: str = ""
    provider: str = ""
    usage: dict[str, Any] = field(default_factory=dict)    # input_tokens, output_tokens, cost_usd, ...
    seconds: float = 0.0


class DirectorLlm(Protocol):
    """Callable used for every Director model call."""

    def __call__(self, *, purpose: str, instructions: str, text: str, images: Sequence[Image] = (),
                 json_schema: dict[str, Any] | None = None, schema_name: str | None = None,
                 temperature: float = 0.7, max_tokens: int = 6000, timeout: float = 240.0) -> LlmReply: ...


class BudgetExceeded(RuntimeError):
    """The run hit its model-call cap."""


class Cancelled(RuntimeError):
    """The user cancelled the run."""


CancelLike = Callable[[], bool] | threading.Event | None


def is_cancelled(cancel: CancelLike) -> bool:
    """True when ``cancel`` (callable or Event) says stop."""
    if cancel is None:
        return False
    if isinstance(cancel, threading.Event):
        return cancel.is_set()
    probe = getattr(cancel, "is_set", None)
    try:
        return bool(probe() if callable(probe) else cancel())
    except Exception:  # noqa: BLE001 - a broken cancel probe must not kill the run
        return False


def _parse_if_json(text: str, wanted: bool) -> Any:
    if not wanted:
        return None
    obj, _err = parse_json_text(text)
    return obj


# ----------------------------------------------------------------------------- Hermes ctx.llm

def hermes_llm(ctx_llm: Any, task: str | None = "showreel") -> DirectorLlm:
    """Adapt ``ctx.llm`` (``agent.plugin_llm.PluginLlm``) to :class:`DirectorLlm`.

    Uses ``complete_structured`` for every call (text + image input blocks). If the ``task`` slot is
    refused (``PluginLlmTrustError``) it retries on the user's main model. If the host validates JSON
    against the schema and rejects a near-miss, it retries once in plain JSON mode so our own validator
    (which can repair) sees the text.
    """
    def call(*, purpose: str, instructions: str, text: str, images: Sequence[Image] = (),
             json_schema: dict[str, Any] | None = None, schema_name: str | None = None,
             temperature: float = 0.7, max_tokens: int = 6000, timeout: float = 240.0) -> LlmReply:
        blocks: list[dict[str, Any]] = [{"type": "text", "text": text}]
        blocks += [{"type": "image", "data": im.data, "mime_type": im.mime_type} for im in images]
        base = dict(instructions=instructions, input=blocks, temperature=temperature, max_tokens=max_tokens,  # noqa: C408
                    timeout=timeout, purpose=f"showreel.{purpose}")
        modes = [dict(json_schema=json_schema, schema_name=schema_name), dict(json_mode=True)] if json_schema \
            else [dict()]  # noqa: C408
        t0 = time.monotonic()
        last_err = "no usable LLM route"
        for mode in modes:
            for slot in ([task, None] if task else [None]):
                try:
                    res = ctx_llm.complete_structured(**base, **mode, task=slot)
                except Exception as exc:  # noqa: BLE001 - provider errors, timeouts, host-side schema mismatch
                    name = type(exc).__name__
                    if slot and name == "PluginLlmTrustError":
                        continue
                    last_err = f"{name}: {exc}"
                    if isinstance(exc, ValueError) and "schema" in str(exc).lower():
                        break                       # next mode: plain JSON
                    return LlmReply(error=last_err, seconds=time.monotonic() - t0)

                txt = getattr(res, "text", "") or ""
                parsed = getattr(res, "parsed", None) if getattr(res, "content_type", "") == "json" else None
                if parsed is None and json_schema is not None:
                    parsed = _parse_if_json(txt, True)
                return LlmReply(text=txt, parsed=parsed, provider=str(getattr(res, "provider", "")),
                                model=str(getattr(res, "model", "")), usage=_usage_dict(getattr(res, "usage", None)),
                                seconds=time.monotonic() - t0)
        return LlmReply(error=last_err, seconds=time.monotonic() - t0)
    return call


_USAGE_KEYS = ("input_tokens", "output_tokens", "total_tokens", "cache_read_tokens", "cache_write_tokens", "cost_usd")


def _usage_dict(usage: Any) -> dict[str, Any]:
    """``PluginLlmUsage`` (or any object/dict with the same fields) -> plain dict."""
    if usage is None:
        return {}
    if isinstance(usage, dict):
        return {k: usage[k] for k in _USAGE_KEYS if usage.get(k) is not None}
    return {k: getattr(usage, k) for k in _USAGE_KEYS if getattr(usage, k, None) is not None}


# ----------------------------------------------------------------------------- dev: hermes chat

def hermes_cli_llm(*, exe: str | None = None, workdir: Path | None = None, extra_turns: int = 1,
                   reasoning: str | None = None) -> DirectorLlm:
    """Dev-only adapter: one ``hermes chat --query-file F -Q --format stream-json`` run per call.

    The user's default model answers through the full agent. One-shot chat cannot attach images
    (``--image`` is refused by the gateway), so images are written to disk and the agent is told to open
    each with its ``vision_analyze`` tool, which attaches the image natively for a vision-capable main model.
    Token counts come from the stream-json ``result`` event (they include the agent's own system prompt and
    tool schemas, so they overstate what the plugin's ``ctx.llm`` route would cost).
    """
    exe = exe or shutil.which("hermes") or ""

    def call(*, purpose: str, instructions: str, text: str, images: Sequence[Image] = (),
             json_schema: dict[str, Any] | None = None, schema_name: str | None = None,
             temperature: float = 0.7, max_tokens: int = 6000, timeout: float = 240.0) -> LlmReply:
        if not exe:
            return LlmReply(error="the `hermes` command is not on PATH")
        t0 = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="showreel-director-", dir=str(workdir) if workdir else None) as tmp:
            paths = []
            for i, im in enumerate(images):
                p = Path(im.path) if im.path and Path(im.path).is_file() else Path(tmp) / f"image{i + 1}.png"
                if not p.is_file():
                    p.write_bytes(im.data)
                paths.append(p.resolve().as_posix())
            query = [instructions, "", text]
            if json_schema is not None:
                query += ["", f"# JSON schema ({schema_name or 'reply'})",
                          json.dumps(json_schema, separators=(",", ":")),
                          "", "Reply with the JSON object only (no prose, no code fences)."]
            if paths:
                listing = "\n".join(f"  {i + 1}. {p}" for i, p in enumerate(paths))
                query = [(f"BEFORE answering, open each of these images with your vision tool (vision_analyze), "
                         f"one call per image, in this order:\n{listing}\nDo not call any other tool. Then do the "
                         "task below, using what you saw."), "", *query]
            else:
                query += ["", "Answer directly: do not call any tools."]
            qf = Path(tmp) / "query.md"
            qf.write_text("\n".join(query), encoding="utf-8")
            cmd = [exe, "chat", "--source", "tool", "--query-file", str(qf), "-Q", "--format", "stream-json",
                   "--max-turns", str(len(paths) + extra_turns)]
            if reasoning:
                cmd += ["--reasoning", reasoning]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                      check=False, timeout=max(120.0, timeout * 3), stdin=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired) as exc:
                return LlmReply(error=f"hermes chat failed: {type(exc).__name__}: {exc}",
                                seconds=time.monotonic() - t0)
        out = parse_stream_json(proc.stdout)
        txt = out.get("text", "")
        usage = {"input_tokens": out.get("input", 0), "output_tokens": out.get("output", 0),
                 "cache_read_tokens": out.get("cache_read", 0), "cache_write_tokens": out.get("cache_write", 0)}
        err = out.get("error", "") or ("" if proc.returncode == 0 and txt else
                                       f"hermes chat exit {proc.returncode}: {proc.stderr.strip()[-300:]}")
        return LlmReply(text=txt, parsed=_parse_if_json(txt, json_schema is not None), error=err,
                        model="hermes chat (default model)", usage=usage, seconds=time.monotonic() - t0)
    return call


def parse_stream_json(stdout: str) -> dict[str, Any]:
    """Final text, token counts and error from ``hermes chat --format stream-json`` output."""
    text_parts: list[str] = []
    result: dict[str, Any] = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "text":
            text_parts.append(str(ev.get("text", "")))
        elif ev.get("type") == "result":
            result = ev
    tokens = result.get("tokens") or {}
    return {"text": (result.get("text") or "".join(text_parts)).strip(), "error": result.get("error") or "",
            "input": int(tokens.get("input", 0) or 0), "output": int(tokens.get("output", 0) or 0),
            "cache_read": int(tokens.get("cache_read", 0) or 0), "cache_write": int(tokens.get("cache_write", 0) or 0),
            "exit_code": result.get("exit_code")}


# ----------------------------------------------------------------------------- ledger

@dataclass
class CallRecord:
    """One persisted call (for the job log and the Desktop pane)."""
    n: int
    purpose: str
    seconds: float
    ok: bool
    error: str = ""
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    images: int = 0


class CallLedger:
    """Wraps a :class:`DirectorLlm`: persists prompts/replies, totals usage, enforces budget + cancel."""

    def __init__(self, llm: DirectorLlm, calls_dir: Path | None, *, max_calls: int,
                 cancel: CancelLike = None) -> None:
        self.llm = llm
        self.calls_dir = calls_dir
        self.max_calls = max_calls
        self.cancel = cancel
        self.records: list[CallRecord] = []
        if calls_dir:
            calls_dir.mkdir(parents=True, exist_ok=True)

    @property
    def remaining(self) -> int:
        return self.max_calls - len(self.records)

    def __call__(self, *, purpose: str, instructions: str, text: str, images: Sequence[Image] = (),
                 json_schema: dict[str, Any] | None = None, schema_name: str | None = None,
                 temperature: float = 0.7, max_tokens: int = 6000, timeout: float = 240.0) -> LlmReply:
        if is_cancelled(self.cancel):
            raise Cancelled("cancelled")
        if len(self.records) >= self.max_calls:
            raise BudgetExceeded(f"model call budget of {self.max_calls} reached")
        n = len(self.records) + 1
        stem = f"{n:02d}-{_slug(purpose)}"
        if self.calls_dir:
            listing = "".join(f"\n[image {i + 1}] {im.label or im.path or im.mime_type}" for i, im in enumerate(images))
            schema = f"\n\n# JSON schema ({schema_name})\n{json.dumps(json_schema, indent=1)}" if json_schema else ""
            _write(self.calls_dir / f"{stem}.prompt.md",
                   f"# {purpose}\n\n## instructions\n{instructions}\n\n## input\n{text}{listing}{schema}\n")
        t0 = time.monotonic()
        try:
            reply = self.llm(purpose=purpose, instructions=instructions, text=text, images=images,
                             json_schema=json_schema, schema_name=schema_name, temperature=temperature,
                             max_tokens=max_tokens, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - adapters should not raise; treat it as an error reply
            reply = LlmReply(error=f"{type(exc).__name__}: {exc}")
        reply.seconds = reply.seconds or (time.monotonic() - t0)
        rec = CallRecord(n, purpose, round(reply.seconds, 2), not reply.error, reply.error[:500], reply.model,
                         dict(reply.usage), len(images))
        self.records.append(rec)
        if self.calls_dir:
            _write(self.calls_dir / f"{stem}.reply.txt", reply.text or f"[error] {reply.error}")
            _write(self.calls_dir / f"{stem}.meta.json", json.dumps(asdict(rec), indent=1))
        return reply

    def totals(self) -> dict[str, Any]:
        """Calls, seconds, tokens and cost so far."""
        def tok(key: str) -> int:
            return sum(int(r.usage.get(key) or 0) for r in self.records)
        costs = [float(c) for r in self.records if (c := r.usage.get("cost_usd")) is not None]
        return {"calls": len(self.records), "failed_calls": sum(not r.ok for r in self.records),
                "seconds": round(sum(r.seconds for r in self.records), 1),
                "input_tokens": tok("input_tokens"), "output_tokens": tok("output_tokens"),
                "cost_usd": round(sum(costs), 4) if costs else None,
                "by_purpose": _by_purpose(self.records)}


def _by_purpose(records: list[CallRecord]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        key = r.purpose.split(":")[0]
        out[key] = out.get(key, 0) + 1
    return out


def _slug(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s.lower())[:48].strip("-") or "call"


def _write(p: Path, text: str) -> None:
    try:
        p.write_text(text, encoding="utf-8")
    except OSError:
        pass
