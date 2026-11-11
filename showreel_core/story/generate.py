"""Storyboard generation: one structured LLM call, one repair call, heuristic fallback.

``llm`` is any callable with the :class:`LlmCall` signature, so tests inject fakes and
the plugin wraps ``ctx.llm`` with :func:`hermes_llm`. The flow never raises:

1. structured call with :func:`schema.transport_schema`;
2. strict schema + semantic validation; an unparseable reply or any ``error`` issue
   triggers ONE repair call that quotes the precise problems and the rejected answer;
3. the best viable candidate wins (auto-fixed, ``source`` "llm" or "repaired");
   otherwise the deterministic heuristic (``source`` "heuristic").
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..contracts import Event, Product, SceneType, Stats, Storyboard, StoryScene
from .facts import SessionFacts
from .heuristic import GENERIC_NAME, build_heuristic_storyboard, infer_product
from .options import StoryOptions
from .prompt import build_input, build_instructions, build_repair_input
from .rules import film_mode
from .schema import (
    SCHEMA_NAME,
    parse_json_text,
    storyboard_from_json,
    transport_schema,
    validate_schema,
)
from .validate import ValidationResult, validate_storyboard

log = logging.getLogger(__name__)


@dataclass
class LlmReply:
    """What one model call returned: raw text, parsed JSON if any, or an error string."""
    text: str = ""
    parsed: Any = None
    error: str = ""
    provider: str = ""
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class LlmCall(Protocol):
    """Callable used for storyboard calls (wrap ``ctx.llm`` with :func:`hermes_llm`)."""

    def __call__(self, *, instructions: str, input_text: str, json_schema: dict[str, Any], schema_name: str,
                 temperature: float, max_tokens: int, timeout: float) -> LlmReply: ...


@dataclass
class Attempt:
    """One LLM attempt and what validation thought of it."""
    kind: str                      # "initial" | "repair"
    accepted: bool
    problems: list[str] = field(default_factory=list)
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0


@dataclass
class GenerationResult:
    """The chosen storyboard plus provenance for logs and the job file."""
    storyboard: Storyboard
    attempts: list[Attempt] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


@dataclass
class _Candidate:
    kind: str
    raw: Any                              # parsed JSON (or raw text) to quote back in a repair
    problems: list[str]
    result: ValidationResult | None       # auto-fixed storyboard when the JSON was schema-valid


def hermes_llm(ctx_llm: Any, task: str | None = "hype") -> LlmCall:
    """Adapt ``ctx.llm`` (``PluginLlm``) to :class:`LlmCall`; exceptions become ``LlmReply.error``.

    If the auxiliary ``task`` slot is refused (not registered), retries once on the
    user's main model; the refused call never reached a model, so it costs nothing.
    """
    def call(*, instructions: str, input_text: str, json_schema: dict[str, Any], schema_name: str,
             temperature: float, max_tokens: int, timeout: float) -> LlmReply:
        kwargs = dict(instructions=instructions, input=[{"type": "text", "text": input_text}],  # noqa: C408
                      json_schema=json_schema, schema_name=schema_name, temperature=temperature,
                      max_tokens=max_tokens, timeout=timeout, purpose="hype.storyboard")
        for slot in ([task, None] if task else [None]):
            try:
                res = ctx_llm.complete_structured(**kwargs, task=slot)
            except Exception as exc:  # noqa: BLE001 - provider errors, timeouts, host-side schema mismatch
                if slot and type(exc).__name__ == "PluginLlmTrustError":
                    continue
                return LlmReply(error=f"{type(exc).__name__}: {exc}")
            usage = getattr(res, "usage", None)
            parsed = getattr(res, "parsed", None) if getattr(res, "content_type", "") == "json" else None
            return LlmReply(text=getattr(res, "text", "") or "", parsed=parsed,
                            provider=str(getattr(res, "provider", "")), model=str(getattr(res, "model", "")),
                            usage=dict(vars(usage)) if usage is not None and hasattr(usage, "__dict__") else {})
        return LlmReply(error="no usable LLM route")
    return call


def generate_storyboard(llm: LlmCall | Callable[..., LlmReply] | None, digest: str, events: list[Event],
                        stats: Stats | None, options: StoryOptions | None = None,
                        product: Product | None = None) -> Storyboard:
    """Storyboard for a session: LLM (validated, repaired once) or the heuristic fallback. Never raises.

    ``product`` is an optional draft from the session stage (shown to the model as a hint).
    """
    return generate_storyboard_report(llm, digest, events, stats, options, product).storyboard


def generate_storyboard_report(llm: LlmCall | Callable[..., LlmReply] | None, digest: str, events: list[Event],
                               stats: Stats | None, options: StoryOptions | None = None,
                               product: Product | None = None) -> GenerationResult:
    """Like :func:`generate_storyboard`, plus attempts, fixes and issues for logging."""
    options = options or StoryOptions()
    options.mode = film_mode(options.mode)
    attempts: list[Attempt] = []
    try:
        facts = SessionFacts(events, stats, digest, timestamps=(options.mode == "speedrun"))
        draft = product or infer_product(facts)
        lock = bool(product is not None and product.name and options.product_name_locked)
        if llm is not None:
            chosen = _llm_storyboard(llm, digest, facts, options, draft, attempts, lock)
            if chosen is not None:
                return GenerationResult(chosen.storyboard, attempts, chosen.fixes, [str(i) for i in chosen.issues])
        sb = build_heuristic_storyboard(events, stats, options, digest, draft)
        res = validate_storyboard(sb, facts, options.clamped_seconds(), options.mode, draft=draft, lock_name=lock)
        res.storyboard.source = "heuristic"
        return GenerationResult(res.storyboard, attempts, res.fixes, [str(i) for i in res.issues])
    except Exception as exc:  # last line of defence: a minimal valid film, never an exception
        log.exception("storyboard generation failed")
        attempts.append(Attempt("fallback", False, [f"{type(exc).__name__}: {exc}"]))
        return GenerationResult(_minimal_storyboard(options, product), attempts)


def _llm_storyboard(llm: Callable[..., LlmReply], digest: str, facts: SessionFacts, options: StoryOptions,
                    draft: Product, attempts: list[Attempt], lock: bool = False) -> ValidationResult | None:
    """Initial call, then one repair when needed; returns the best viable fixed storyboard or None."""
    instructions = build_instructions(options)
    input_text = build_input(digest, facts, options, draft, name_locked=lock)
    first = _attempt(llm, "initial", instructions, input_text, facts, options, attempts, draft, lock)
    if first.result is not None and first.result.viable and not first.result.errors:
        first.result.storyboard.source = "llm"
        return first.result
    repair_input = build_repair_input(input_text, first.raw, first.problems)
    second = _attempt(llm, "repair", instructions, repair_input, facts, options, attempts, draft, lock)
    viable = [c for c in (second, first) if c.result is not None and c.result.viable]
    if not viable:
        return None
    best = min(viable, key=lambda c: len(c.result.errors))  # type: ignore[union-attr]
    assert best.result is not None
    best.result.storyboard.source = "repaired" if best.kind == "repair" else "llm"
    return best.result


def _attempt(llm: Callable[..., LlmReply], kind: str, instructions: str, input_text: str, facts: SessionFacts,
             options: StoryOptions, attempts: list[Attempt], draft: Product | None = None,
             lock: bool = False) -> _Candidate:
    """Run one call, validate it, record the attempt."""
    started = time.monotonic()
    try:
        reply = llm(instructions=instructions, input_text=input_text, json_schema=transport_schema(),
                    schema_name=SCHEMA_NAME, temperature=options.temperature, max_tokens=options.max_tokens,
                    timeout=options.timeout)
    except Exception as exc:  # noqa: BLE001 - a misbehaving adapter is just a failed attempt
        reply = LlmReply(error=f"{type(exc).__name__}: {exc}")
    elapsed = time.monotonic() - started
    if not isinstance(reply, LlmReply):
        reply = LlmReply(error=f"adapter returned {type(reply).__name__}, expected LlmReply")
    obj: Any = reply.parsed
    problems: list[str] = []
    if obj is None:
        if reply.error and not reply.text:
            problems.append(f"$: the model call failed ({reply.error}); return the storyboard JSON object")
        else:
            obj, err = parse_json_text(reply.text)
            if obj is None:
                problems.append(f"$: {err}; return exactly one JSON object")
    result: ValidationResult | None = None
    if obj is not None:
        schema_errors = validate_schema(obj)
        problems += [str(e) for e in schema_errors]
        if not schema_errors:
            sb = storyboard_from_json(obj, source="llm", mode=options.mode)
            result = validate_storyboard(sb, facts, options.clamped_seconds(), options.mode, draft=draft,
                                         lock_name=lock)
            problems += [str(i) for i in result.errors]
            if not result.viable:
                problems.append("$.scenes: after removing invalid scenes the film has too little left")
    accepted = result is not None and result.viable and not result.errors
    attempts.append(Attempt(kind, accepted, problems, reply.model, reply.usage, round(elapsed, 2)))
    return _Candidate(kind, obj if obj is not None else reply.text, problems, result)


def _minimal_storyboard(options: StoryOptions, product: Product | None) -> Storyboard:
    name = product.name if product and product.name else GENERIC_NAME
    scenes = [StoryScene(SceneType.TITLE, [], "", ""), StoryScene(SceneType.END, [], "", "")]
    return Storyboard(title=name, tagline="", scenes=scenes, cta="", source="heuristic",
                      mode=film_mode(options.mode), product=product or Product(name=name))  # type: ignore[arg-type]
