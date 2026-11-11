"""Capability tiers: how much of the Director's work the model is trusted with.

The engine adapts to the model instead of assuming a frontier model:

| tier     | path                                   | custom scene code | critic                          |
|----------|----------------------------------------|-------------------|---------------------------------|
| strong   | free: treatment -> film script (+code) | yes (<= budget)   | vision critic                   |
| standard | free, kit-only (no custom code)        | no                | vision critic when it can see   |
| weak     | compose: pick -> words -> engine film  | no                | measured checks (+ vision opt.) |

Every tier lands on the same floor: when a step fails validation after its repairs, the next-simpler path runs
(free -> compose -> engine floor without any model), so a weak or broken model still yields a well-made film.
A model without vision is never asked to critique pictures; the engine scores the film from measurements.

Detection is a best guess from the model id (configurable: ``director_tier`` / ``director_vision`` options or the
dev harness ``--tier`` / ``--no-vision``); unknown models get ``standard`` with vision.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

TIERS = ("strong", "standard", "weak")

_WEAK = re.compile(r"haiku|flash|(?<!ge)mini\b|-mini|nano|lite|small|tiny|\b\d{1,2}b\b|-\d{1,2}b|gemma|phi-?\d|"
                   r"llama-?3\.?[12]?-?[0-9]*b?|mistral-(small|7b)|qwen[^/]*?(0\.5|1\.5|3|4|7|8|14)b|"
                   r"deepseek[^/]*flash|glm[^/]*flash|minimax[^/]*flash|local|ollama", re.IGNORECASE)
_STRONG = re.compile(r"opus|fable|mythos|gpt-5(\.\d)?(-sol)?$|gpt-5\.\d-sol|o3\b|o4\b|gemini-[\d.]+-pro|"
                     r"grok-4(?!.*mini)|sonnet-5", re.IGNORECASE)
_NO_VISION = re.compile(r"deepseek|glm-[\d.]+(?!v)|minimax|qwen(?!.*vl)|llama-?3(?!\.2-?\d+b-vision)|"
                        r"mistral(?!.*pix)|codestral|abliterated|hermes-?[234]\b|gpt-oss|kimi-k2(?!\.5)", re.IGNORECASE)
_SMALL_CTX = re.compile(r"\b\d{1,2}b\b|-\d{1,2}b|gemma|phi|local|ollama", re.IGNORECASE)


@dataclass(frozen=True)
class Tier:
    """What the engine asks of this model."""
    name: str                 # strong | standard | weak
    model: str = ""
    vision: bool = True       # the critic can look at contact sheets
    context: int = 200_000    # tokens the prompts may use (catalog text is clipped to fit)
    custom_scenes: int = 3    # max custom scene modules the model may write (0 = kit/library scenes only)
    path: str = "free"        # free (treatment -> film) | compose (pick -> words -> engine-assembled film)
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect(model: str = "", *, configured: str = "", vision: Any = None, context: int | None = None,
           max_custom: int = 3) -> Tier:
    """The tier for ``model`` (an id like ``claude-haiku-4-5``), honouring explicit configuration."""
    m = str(model or "").strip()
    conf = str(configured or "").strip().lower()
    if conf in TIERS:
        name, why = conf, "configured"
    elif _WEAK.search(m):
        name, why = "weak", f"model id {m!r} looks small/fast"
    elif _STRONG.search(m):
        name, why = "strong", f"model id {m!r} looks frontier-class"
    elif m:
        name, why = "standard", f"unknown model {m!r}"
    else:
        name, why = "strong", "the user's main model (no id given)"
    if isinstance(vision, str):
        vision = {"true": True, "yes": True, "1": True, "on": True,
                  "false": False, "no": False, "0": False, "off": False}.get(vision.strip().lower())
    sees = bool(vision) if isinstance(vision, bool) else not (m and _NO_VISION.search(m))
    ctx = int(context) if context else (32_000 if m and _SMALL_CTX.search(m) else 200_000)
    if ctx < 60_000 and name == "strong":
        name, why = "standard", why + "; small context"
    custom = max_custom if name == "strong" else 0
    path = "compose" if name == "weak" else "free"
    return Tier(name, m, sees, ctx, custom, path, why)


def host_model() -> str:
    """The user's main model id from the host's config ('' outside Hermes, unset, or a MoA preset).

    ``ctx.llm`` carries no model id before a call (only its results do), so inside the plugin every model looked
    like "the user's main model" and took the strong path; Hermes answers ``ctx.llm`` calls with this model."""
    try:
        from hermes_cli.config import load_config_readonly  # inside Hermes only (lazy); never mutate the result
        cfg = load_config_readonly()
    except Exception:  # noqa: BLE001 - outside Hermes / an older host: unknown
        return ""
    m = cfg.get("model") if isinstance(cfg, dict) else None
    if isinstance(m, dict):
        if str(m.get("provider") or "").strip().lower() == "moa":
            return ""
        m = m.get("default") or m.get("model")
    return m.strip() if isinstance(m, str) else ""


def model_of(llm: Any) -> str:
    """Best-effort model id of a ``ctx.llm`` / adapter object (empty when unknown)."""
    for obj in (llm, getattr(llm, "llm", None), getattr(llm, "__wrapped__", None)):
        if obj is None:
            continue
        for attr in ("model", "model_id", "model_name", "default_model"):
            v = getattr(obj, attr, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
        info = getattr(obj, "info", None)
        if callable(info):
            try:
                d = info()
            except Exception:  # noqa: BLE001 - optional host API
                d = None
            if isinstance(d, dict) and isinstance(d.get("model"), str):
                return d["model"]
    return ""
