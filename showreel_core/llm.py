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
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

PLUGIN = "showreel"
AUX_TASK = "showreel"

Dispatch = Callable[..., str]


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

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def complete_structured(self, **kwargs: Any) -> Any:
        schema = kwargs.pop("json_schema", None)
        wants_json = bool(kwargs.pop("json_mode", False)) or schema is not None
        if not wants_json:
            return self._llm.complete_structured(**kwargs)
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
                return self._llm.complete_structured(**kwargs, json_mode=True)
            except Exception as exc:
                if not _json_mode_refused(exc):
                    raise
                JsonModeLlm.plain_only = True
                log.info("showreel: the model route refused JSON mode (%s); using plain-text JSON replies", exc)
        return self._llm.complete_structured(**kwargs)

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

    def story_call(self) -> Any:
        """The storyboard LLM route (``story.LlmCall``) or ``None`` (-> heuristic storyboard)."""
        if self.story_llm is not None:
            return self.story_llm
        if self.llm is None:
            return None
        from .story import hermes_llm
        return hermes_llm(JsonModeLlm(self.llm), task=AUX_TASK)

    def emit(self, event: str, payload: dict[str, Any]) -> None:
        """Broadcast a plugin event (never raises)."""
        if self.broadcast is None:
            return
        try:
            self.broadcast(event, payload)
        except Exception as exc:  # noqa: BLE001 - UI push is best effort
            log.debug("showreel event %s failed: %s", event, exc)


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
            log.warning("showreel: ctx.llm unavailable (%s); using the heuristic storyboard", exc)
            return None

    dispatch: Any = getattr(ctx, "dispatch_tool", None)
    post: Any = getattr(ctx, "post_message", None)
    return Host(llm=llm(), dispatch=dispatch if callable(dispatch) else None,
                post=post if callable(post) else None, broadcast=_broadcaster(), surface=surface, label="plugin")


def _registry_dispatch() -> Dispatch | None:
    try:
        from tools.registry import registry  # public, lazy
    except Exception as exc:  # noqa: BLE001
        log.info("showreel: tools.registry unavailable (%s); captions only", exc)
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
        log.info("showreel: PluginLlm unavailable outside ctx (%s)", exc)
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
                f"not applied; remove tts.{provider}.speed to let Showreel set the pace")
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
    Hermes venv that still pins 7.2.x narrates nothing. Showreel never upgrades packages in the Hermes venv;
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
