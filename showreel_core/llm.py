"""Adapters between the pipeline and Hermes services (``ctx.llm``, ``ctx.dispatch_tool``, messages, events).

The pipeline never touches ``ctx`` directly; it gets a :class:`Host`. Three ways to build one:

- :func:`host_from_ctx` inside the plugin (slash command, tools, CLI);
- :func:`standalone_host` inside ``dashboard/plugin_api.py`` (no ``ctx`` there): the public
  ``agent.plugin_llm.PluginLlm`` facade and ``tools.registry`` dispatch, both imported lazily;
- the dev harness (``python -m showreel_core.pipeline``): ``hermes chat`` one-shot for the
  storyboard and edge-tts / captions-only for narration.
"""
from __future__ import annotations

import json
import logging
import random
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

PLUGIN = "hype"
AUX_TASK = "hype"

Dispatch = Callable[..., str]


# --------------------------------------------------------------------------- transient model failures

#: Waits before retry 1, 2, 3 of a call that failed with a transient error (rate limit, overloaded, 5xx, a fast
#: timeout); each gets +-25 % jitter and a ``Retry-After`` from the provider wins when it is longer. Real E2E: the
#: storyboard call met HTTP 429 and the next call went out 0.1 s later, met the same 429, and the film fell back.
RETRY_DELAYS_S: tuple[float, ...] = (4.0, 12.0, 30.0)
#: Most time one call may spend waiting between its tries (a call never sleeps past this, so a job cannot hang).
RETRY_BUDGET_S = 60.0
#: After a call used up its retries on a transient error, later calls of the same job try once without waiting
#: for this long (re-armed by each further failure): a provider that rate-limits every call (one key shared by
#: parallel users, a per-model hourly cap) costs the job one minute, not one minute per call.
COOLDOWN_S = 45.0

_RATE_RE = re.compile(r"rate[ _-]?limit|ratelimit|too many requests|\b429\b|quota exceeded|requests per", re.I)
_OVERLOAD_RE = re.compile(r"overloaded|\b529\b|at capacity|server is busy|temporarily unavailable|"
                          r"service unavailable|try again later", re.I)
_SERVER_RE = re.compile(r"(?:error code|status(?: code)?|http)\W{0,3}5\d\d\b|internal server error|bad gateway|"
                        r"gateway time-?out", re.I)
_TIMEOUT_RE = re.compile(r"timed? ?out|timeout|deadline exceeded", re.I)
_RETRY_AFTER_TEXT = re.compile(r"(?:retry|try again)(?: after| in)?\s+(\d+(?:\.\d+)?)\s*(ms|s|sec|seconds?)?\b", re.I)


def _status_of(exc: BaseException) -> int | None:
    for obj in (exc, getattr(exc, "response", None)):
        code = getattr(obj, "status_code", None) if obj is not None else None
        if isinstance(code, int):
            return code
    return None


def transient_kind(exc: BaseException) -> str:
    """``rate_limit`` | ``overloaded`` | ``server`` | ``timeout`` for a failure worth waiting out, else ``""``
    (bad request, auth, billing, a refused JSON format: retrying those only repeats the error)."""
    name = type(exc).__name__
    text = f"{name}: {exc}"
    status = _status_of(exc)
    low = text.lower()
    if any(k in low for k in ("credit", "billing", "insufficient", "payment", "unauthor", "invalid api key",
                              "permission")) and status != 529:
        return ""
    if name == "RateLimitError" or status == 429 or _RATE_RE.search(text):
        return "rate_limit"
    if status == 529 or name in ("OverloadedError", "ServiceUnavailableError") or _OVERLOAD_RE.search(text):
        return "overloaded"
    if (isinstance(status, int) and 500 <= status < 600) or name == "InternalServerError" or _SERVER_RE.search(text):
        return "server"
    if isinstance(exc, TimeoutError) or "timeout" in name.lower() or _TIMEOUT_RE.search(text):
        return "timeout"
    if name in ("APIConnectionError", "ConnectionError", "RemoteProtocolError", "ConnectError", "ReadError"):
        return "server"
    return ""


def retry_after_s(exc: BaseException) -> float | None:
    """The provider's ``Retry-After`` (headers on the exception or its response, or the message text), seconds."""
    for obj in (exc, getattr(exc, "response", None)):
        headers = getattr(obj, "headers", None) if obj is not None else None
        if headers is None:
            continue
        try:
            ms = headers.get("retry-after-ms")
            if ms not in (None, ""):
                return max(0.0, float(ms) / 1000.0)
            val = headers.get("retry-after")
            if val not in (None, ""):
                return max(0.0, float(val))
        except (AttributeError, TypeError, ValueError):
            continue
    direct = getattr(exc, "retry_after", None)
    if isinstance(direct, (int, float)):
        return max(0.0, float(direct))
    m = _RETRY_AFTER_TEXT.search(str(exc))
    if m:
        val = float(m.group(1))
        return val / 1000.0 if (m.group(2) or "").lower() == "ms" else val
    return None


#: What the user reads when the model could not be reached (job notes, done text, Desktop pane).
KIND_TEXT = {"rate_limit": "the model was rate-limited", "overloaded": "the model service was overloaded",
             "server": "the model service had an error", "timeout": "the model did not answer in time"}


@dataclass
class CallTally:
    """Model calls of one job: how many went out, failed and why (thread-safe; the Director calls in parallel).

    The pipeline reads it to tell the user the truth ("the model was rate-limited, so Hype used its own
    storyboard") instead of "the model's reply could not be used", and to flag a Directed film that never reached
    the model."""
    calls: int = 0
    ok: int = 0
    failed: int = 0
    kinds: dict[str, int] = field(default_factory=dict)
    retries: int = 0
    waited_s: float = 0.0
    cooldown_until: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"calls": self.calls, "ok": self.ok, "failed": self.failed, "kinds": dict(self.kinds),
                    "retries": self.retries, "waited_s": round(self.waited_s, 1)}

    def record(self, ok: bool, kind: str = "") -> None:
        with self._lock:
            self.calls += 1
            if ok:
                self.ok += 1
            else:
                self.failed += 1
                key = kind or "other"
                self.kinds[key] = self.kinds.get(key, 0) + 1

    def since(self, before: dict[str, Any]) -> dict[str, Any]:
        """Counts added after ``before`` (a :meth:`snapshot`)."""
        now = self.snapshot()
        kinds = {k: v - before.get("kinds", {}).get(k, 0) for k, v in now["kinds"].items()}
        return {"calls": now["calls"] - before.get("calls", 0), "ok": now["ok"] - before.get("ok", 0),
                "failed": now["failed"] - before.get("failed", 0), "kinds": {k: v for k, v in kinds.items() if v}}


def failure_reason(delta: dict[str, Any]) -> str:
    """Plain words for why a stage's model calls failed (``KIND_TEXT``), ``""`` when none failed transiently."""
    kinds = delta.get("kinds") or {}
    for kind in ("rate_limit", "overloaded", "server", "timeout"):
        if kinds.get(kind):
            return KIND_TEXT[kind]
    return ""


def call_with_retries(fn: Callable[[], Any], *, tally: CallTally | None = None, timeout: float | None = None,
                      stop: Callable[[], bool] | None = None, delays: tuple[float, ...] | None = None,
                      budget_s: float | None = None, sleep: Callable[[float], None] = time.sleep) -> Any:
    """``fn()`` with bounded retries on transient failures: at most ``len(delays)`` retries, at most ``budget_s``
    seconds asleep in total, ``Retry-After`` honoured (a wait longer than what is left of the budget is not
    started), jitter on every wait, and no retry of a timeout that used most of its own time limit. ``stop()``
    (the job's cancel flag) ends the waiting at once. Re-raises the last error when the retries run out."""
    tally = tally or CallTally()
    delays = RETRY_DELAYS_S if delays is None else delays
    budget = RETRY_BUDGET_S if budget_s is None else budget_s
    cooling = time.monotonic() < tally.cooldown_until
    attempt, slept = 0, 0.0
    while True:
        t0 = time.monotonic()
        try:
            out = fn()
        except Exception as exc:
            kind = transient_kind(exc)
            took = time.monotonic() - t0
            if kind == "timeout" and (not timeout or took >= 0.5 * float(timeout)):
                kind_retry = False                  # it used its time (or has no known limit): a retry doubles it
            else:
                kind_retry = bool(kind)
            if not kind_retry or cooling or attempt >= len(delays):
                tally.record(False, kind)
                if kind:
                    with tally._lock:
                        tally.cooldown_until = time.monotonic() + COOLDOWN_S
                raise
            wait = delays[attempt] * random.uniform(0.75, 1.25)
            after = retry_after_s(exc)
            if after is not None:
                wait = max(wait, after + random.uniform(0.0, 1.0))
            if slept + wait > budget:
                tally.record(False, kind)
                with tally._lock:
                    tally.cooldown_until = time.monotonic() + COOLDOWN_S
                raise
            log.info("hype: model call failed (%s: %s); retry %d in %.1f s", kind, str(exc)[:160], attempt + 1, wait)
            left = wait
            while left > 0:
                if stop is not None and stop():
                    tally.record(False, kind)
                    raise
                step = min(0.25, left)
                sleep(step)
                left -= step
            slept += wait
            attempt += 1
            with tally._lock:
                tally.retries += 1
                tally.waited_s += wait
            continue
        tally.record(True)
        with tally._lock:
            tally.cooldown_until = 0.0
        return out


def _json_mode_refused(exc: BaseException) -> bool:
    """True when the provider rejected the JSON-output request itself (HTTP 400 about the format/schema)."""
    msg = f"{type(exc).__name__}: {exc}".lower()
    return ("400" in msg or "badrequest" in msg or "invalid_request" in msg) and any(
        k in msg for k in ("schema", "response_format", "output_config", "json"))


class JsonModeLlm:
    """``ctx.llm`` proxy for JSON replies that works on every provider: the schema goes into the prompt as text.

    Real E2E on Anthropic (Hermes 0.22.5): provider-native structured output answered the storyboard schema with
    HTTP 400 "Schema is too complex" after ~3 minutes per attempt, and Hermes' ``json_mode`` maps to an
    ``output_config`` schema Anthropic rejects at once ("'additionalProperties' must be explicitly set to false").
    So: schema as prompt text, JSON mode first, and on a format refusal plain text from then on in this process
    (the callers parse JSON out of the text; :mod:`showreel_core.story.validate` checks and repairs it).
    """

    #: Set once a provider refused JSON mode: later calls in this process go straight to plain text.
    plain_only = False

    def __init__(self, llm: Any, *, tally: CallTally | None = None, stop: Callable[[], bool] | None = None) -> None:
        self._llm = llm
        self.tally = tally if tally is not None else CallTally()
        self.stop = stop

    def _call(self, **kwargs: Any) -> Any:
        """One host call with bounded retries on rate limits, overload, 5xx and fast timeouts."""
        return call_with_retries(lambda: self._llm.complete_structured(**kwargs), tally=self.tally,
                                 timeout=kwargs.get("timeout"), stop=self.stop)

    def complete_structured(self, **kwargs: Any) -> Any:
        schema = kwargs.pop("json_schema", None)
        wants_json = bool(kwargs.pop("json_mode", False)) or schema is not None
        if not wants_json:
            return self._call(**kwargs)
        head = str(kwargs.get("instructions", "")).rstrip()
        if schema is not None:
            try:
                text = json.dumps(schema, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                text = str(schema)
            head += "\n\nReply with ONE JSON object that follows this JSON schema:\n" + text
        kwargs["instructions"] = head + ("\n\nReply with only that JSON object: no prose before or after it, "
                                         "no markdown fences.")
        if not JsonModeLlm.plain_only:
            try:
                return self._call(**kwargs, json_mode=True)
            except Exception as exc:
                if not _json_mode_refused(exc):
                    raise
                JsonModeLlm.plain_only = True
                log.info("hype: the model route refused JSON mode (%s); using plain-text JSON replies", exc)
        return self._call(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._llm, name)


@dataclass
class Host:
    """Hermes services available to one job (every field optional; missing ones degrade)."""
    llm: Any = None                                  # PluginLlm-like: .complete_structured(...)
    dispatch: Dispatch | None = None                 # ctx.dispatch_tool(name, args) -> JSON str
    post: Callable[[str], Any] | None = None         # ctx.post_message(text) -> handle with .edit(text)
    broadcast: Callable[[str, dict[str, Any]], Any] | None = None   # (event, payload) -> None
    story_llm: Any = None                            # explicit story.LlmCall (dev harness), wins over ``llm``
    surface: str = ""
    label: str = "plugin"                            # where it came from: plugin | dashboard | dev
    calls: CallTally = field(default_factory=CallTally)   # this job's model calls (retries, failures and why)
    stop: Callable[[], bool] | None = None           # the job's cancel flag: ends retry waits at once

    def json_llm(self) -> Any:
        """``llm`` as a :class:`JsonModeLlm` sharing this job's call tally and cancel flag (``None`` without one)."""
        if self.llm is None:
            return None
        if isinstance(self.llm, JsonModeLlm):
            self.llm.tally = self.calls
            if self.llm.stop is None:
                self.llm.stop = self.stop
            return self.llm
        return JsonModeLlm(self.llm, tally=self.calls, stop=lambda: bool(self.stop and self.stop()))

    def story_call(self) -> Any:
        """The storyboard LLM route (``story.LlmCall``) or ``None`` (-> heuristic storyboard)."""
        if self.story_llm is not None:
            return self.story_llm
        if self.llm is None:
            return None
        from .story import hermes_llm
        return hermes_llm(self.json_llm(), task=AUX_TASK)

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        """Broadcast a plugin event (never raises)."""
        if self.broadcast is None:
            return
        try:
            self.broadcast(event, payload)
        except Exception as exc:  # noqa: BLE001 - UI push is best effort
            log.debug("hype event %s failed: %s", event, exc)


def _broadcaster() -> Callable[[str, dict[str, Any]], Any] | None:
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event  # public, lazy
    except Exception:  # noqa: BLE001 - not inside Hermes
        return None
    return lambda event, payload: broadcast_plugin_event(PLUGIN, event, payload)


def host_from_ctx(ctx: Any, *, surface: str = "") -> Host:
    """A :class:`Host` backed by the plugin context (each service probed, never raises)."""
    def llm() -> Any:
        try:
            return ctx.llm
        except Exception as exc:  # noqa: BLE001 - PluginLlm import can fail on odd installs
            log.warning("hype: ctx.llm unavailable (%s); using the heuristic storyboard", exc)
            return None

    dispatch: Any = getattr(ctx, "dispatch_tool", None)
    post: Any = getattr(ctx, "post_message", None)
    return Host(llm=llm(), dispatch=dispatch if callable(dispatch) else None,
                post=post if callable(post) else None, broadcast=_broadcaster(), surface=surface, label="plugin")


def _registry_dispatch() -> Dispatch | None:
    try:
        from tools.registry import registry  # public, lazy
    except Exception as exc:  # noqa: BLE001
        log.info("hype: tools.registry unavailable (%s); captions only", exc)
        return None

    def dispatch(name: str, args: dict[str, Any], **kw: Any) -> str:
        res = registry.dispatch(name, args, **kw)
        return res if isinstance(res, str) else json.dumps(res, default=str)
    return dispatch


def standalone_host() -> Host:
    """A :class:`Host` without ``ctx`` (dashboard API): PluginLlm facade + tools.registry dispatch."""
    llm = None
    try:
        from agent.plugin_llm import PluginLlm  # public facade, lazy
        llm = PluginLlm(plugin_id=PLUGIN)
    except Exception as exc:  # noqa: BLE001
        log.info("hype: PluginLlm unavailable outside ctx (%s)", exc)
    return Host(llm=llm, dispatch=_registry_dispatch(), broadcast=_broadcaster(), surface="desktop", label="dashboard")


# --------------------------------------------------------------------------- TTS pace

#: Providers whose own ``tts.<provider>.speed`` wins over the per-call ``speed`` argument
#: (Hermes reads ``provider_config.get("speed", tts_config.get("speed"))``; the per-call value lands in
#: ``tts_config["speed"]``). Seen in tools/tts_tool_providers.py (edge, xai), tts_tool_openai.py
#: (openai, deepinfra) and tts_command_provider.py (command providers), v0.22.5 and main @5d12e89.
_SECTION_SPEED_WINS = frozenset({"edge", "openai", "xai", "deepinfra"})
#: Providers that never read the top-level/per-call speed at all.
_NO_CALL_SPEED = frozenset({"minimax", "kittentts"})


def tts_speed_conflict(requested: float, tts_config: dict[str, Any] | None = None) -> str | None:
    """Why a per-call ``text_to_speech`` ``speed`` would be ignored on this install, or ``None``.

    Reads only the ``tts`` section of ``<HERMES_HOME>/config.yaml`` (read-only, no secrets live there);
    returns ``None`` whenever that cannot be read. ``tts_config`` lets tests pass the section directly.
    """
    if abs(float(requested) - 1.0) < 1e-6:
        return None
    if tts_config is None:
        try:
            import yaml  # Hermes core dependency
            from hermes_constants import get_hermes_home  # public, lazy
            raw = yaml.safe_load((get_hermes_home() / "config.yaml").read_text(encoding="utf-8")) or {}
            tts_config = raw.get("tts") or {}
        except Exception:  # noqa: BLE001 - outside Hermes / unreadable config: nothing to report
            return None
    if not isinstance(tts_config, dict):
        return None
    provider = str(tts_config.get("provider") or "edge").strip().lower()
    raw_section = tts_config.get(provider)
    section: dict[str, Any] = raw_section if isinstance(raw_section, dict) else {}
    if provider in _NO_CALL_SPEED:
        return (f"the '{provider}' TTS provider ignores per-call speed, so narration plays at its configured "
                f"pace instead of x{requested:g}")
    if provider in _SECTION_SPEED_WINS and section.get("speed") not in (None, ""):
        return (f"tts.{provider}.speed={section['speed']} in config.yaml overrides the per-call speed "
                f"x{requested:g} (Hermes reads the provider speed first), so this style's narration pace is "
                f"not applied; remove tts.{provider}.speed to let Hype set the pace")
    return None


#: First edge-tts release Microsoft's speech endpoint accepts again (7.2.x handshakes get HTTP 403).
EDGE_TTS_MIN = (7, 3)


def tts_provider(tts_config: dict[str, Any] | None = None) -> str:
    """The configured Hermes TTS provider (``tts.provider``, default ``edge``); read-only."""
    if tts_config is None:
        try:
            import yaml  # Hermes core dependency
            from hermes_constants import get_hermes_home  # public, lazy
            raw = yaml.safe_load((get_hermes_home() / "config.yaml").read_text(encoding="utf-8")) or {}
            tts_config = raw.get("tts") or {}
        except Exception:  # noqa: BLE001
            tts_config = {}
    if not isinstance(tts_config, dict):
        tts_config = {}
    return str(tts_config.get("provider") or "edge").strip().lower()


def edge_tts_problem(provider: str | None = None, version: str | None = None) -> str | None:
    """Why Hermes' Edge narration will fail on this install, or ``None``.

    Microsoft's endpoint rejects edge-tts older than 7.3 with HTTP 403 (``WSServerHandshakeError``), so a
    Hermes venv that still pins 7.2.x narrates nothing. Hype never upgrades packages in the Hermes venv;
    it says so and makes a captions-only film. ``version`` lets tests pass the installed version.
    """
    provider = provider or tts_provider()
    if provider != "edge":
        return None
    if version is None:
        try:
            from importlib.metadata import version as _version
            version = _version("edge-tts")
        except Exception:  # noqa: BLE001 - not installed: Hermes reports that itself
            return None
    try:
        parts = tuple(int(p) for p in str(version).split(".")[:2])
    except ValueError:
        return None
    if parts >= EDGE_TTS_MIN:
        return None
    return (f"edge-tts {version} in the Hermes environment is older than 7.3; Microsoft's speech service refuses it "
            "(HTTP 403), so Edge narration fails and films are captions-only. Updating Hermes brings edge-tts 7.3.1+.")


# --------------------------------------------------------------------------- dev routes

def edge_tts_dispatch(voice: str = "en-US-AndrewMultilingualNeural") -> Dispatch | None:
    """Dev stand-in for Hermes ``text_to_speech`` with its default provider (edge-tts), or ``None``.

    Returns Hermes's result envelope so the runtime TTS path (``audio.tts.synthesize``) is the same.
    """
    try:
        import asyncio

        import edge_tts  # dev venv only; Hermes uses its own provider via dispatch_tool
    except Exception:  # noqa: BLE001
        return None

    def dispatch(name: str, args: dict[str, Any], **_kw: Any) -> str:
        if name != "text_to_speech":
            return json.dumps({"success": False, "error": f"unknown tool {name}"})
        out = str(args["output_path"])
        kwargs: dict[str, Any] = {}
        speed = float(args.get("speed") or 1.0)
        if speed != 1.0:   # the same mapping as Hermes' _generate_edge_tts
            kwargs["rate"] = f"{round((speed - 1.0) * 100):+d}%"
        try:
            asyncio.run(edge_tts.Communicate(str(args["text"]), voice, **kwargs).save(out))
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"})
        return json.dumps({"success": True, "file_path": out, "file_paths": [out], "provider": f"edge:{voice}",
                           "media_tag": f"MEDIA:{out}"})
    return dispatch


def hermes_cli_story_llm() -> Any:
    """Dev storyboard route: one ``hermes chat --query-file`` call with the user's default model."""
    import importlib
    harness = importlib.import_module(f"{__package__}.story.try")   # module named after its CLI command
    return harness.hermes_cli_adapter()
