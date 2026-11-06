"""SceneCtx: what a Blender scene module's ``build(sc)`` / ``cues(sc)`` receive (runs INSIDE Blender's Python).

Built by ``entry.py`` from job.json (BLENDER.md "job.json"). Time: shot-local frames ``1..frame_count``;
frame ``f`` <-> ``t = (f - 1) / fps + t_start`` where ``t_start`` is ``-handles[0]`` (frames rendered before the
shot's t0 for an incoming transition). ``dur`` is the shot duration WITHOUT handles; ``span`` is what is rendered.

Library access: ``sc.lib.camera`` / ``sc.lib.flyers`` / ... import ``blender_kits.lib.<name>`` lazily, so a scene
only pays for (and only breaks on) the modules it uses.
"""
from __future__ import annotations

import importlib
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ParamError(ValueError):
    """A scene param failed validation against the module's PARAMS schema."""


class _Lib:
    """``sc.lib.<name>`` -> ``blender_kits.lib.<name>`` (imported on first access)."""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return importlib.import_module(f"blender_kits.lib.{name}")


def _coerce(name: str, spec: dict[str, Any], value: Any) -> Any:
    typ = spec.get("type")
    if value is None:
        return None
    if typ == "enum":
        values = list(spec.get("values") or [])
        if values and value not in values:
            raise ParamError(f"param {name!r}: {value!r} is not one of {values}")
        return value
    if typ in ("float", "number"):
        v = float(value)
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None:
            v = max(float(lo), v)
        if hi is not None:
            v = min(float(hi), v)
        return v
    if typ == "int":
        v = int(round(float(value)))
        lo, hi = spec.get("min"), spec.get("max")
        if lo is not None:
            v = max(int(lo), v)
        if hi is not None:
            v = min(int(hi), v)
        return v
    if typ == "bool":
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if typ in ("string", "str", "text", "asset", "color"):
        return str(value)
    if typ == "list" and not isinstance(value, list):
        raise ParamError(f"param {name!r}: expected a list, got {type(value).__name__}")
    return value


def resolve_params(schema: dict[str, Any] | None, given: dict[str, Any] | None) -> dict[str, Any]:
    """Defaults from the module's PARAMS schema overlaid with the job's params (validated/coerced).

    Unknown keys are kept as-is (scenes may accept extra free-form keys); keys starting with ``_`` are
    pipeline-private and passed through.
    """
    schema = schema or {}
    out: dict[str, Any] = {}
    for name, spec in schema.items():
        spec = spec if isinstance(spec, dict) else {"default": spec}
        out[name] = spec.get("default")
    for name, value in (given or {}).items():
        spec = schema.get(name)
        out[name] = _coerce(name, spec, value) if isinstance(spec, dict) else value
    return out


@dataclass
class SceneCtx:
    """Per-render context for one Blender shot (see BLENDER.md)."""

    params: dict[str, Any]
    fps: int
    dur: float
    frames: int
    res: tuple[int, int]
    aspect: str
    seed: int
    tier: str
    assets: dict[str, dict[str, Any]]
    product: dict[str, Any] | None
    out_dir: Path
    scene: Any = None                       # bpy.types.Scene being built
    handles: tuple[float, float] = (0.0, 0.0)
    handoff: dict[str, Any] | None = None   # {"from_shot", "still": abs path} when the shot takes a handoff still
    alpha: bool = False
    kit_root: Path | None = None
    job: dict[str, Any] = field(default_factory=dict)
    rng: random.Random = field(init=False)
    lib: _Lib = field(init=False, default_factory=_Lib)
    _cues: list[dict[str, Any]] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    # ---- time
    @property
    def t_start(self) -> float:
        """Shot-local time of frame 1 (negative when there is a pre-handle)."""
        return -float(self.handles[0])

    @property
    def span(self) -> float:
        """Rendered seconds: handles + dur."""
        return self.frames / float(self.fps)

    def t(self, frame: float) -> float:
        """Shot-local seconds of (float) frame ``frame`` (frame 1 = ``t_start``)."""
        return (float(frame) - 1.0) / self.fps + self.t_start

    def frame(self, t: float) -> float:
        """Float frame number for shot-local seconds ``t`` (inverse of :meth:`t`). Use ``round()`` for keys."""
        return (float(t) - self.t_start) * self.fps + 1.0

    def u(self, frame: float) -> float:
        """0..1 progress through the shot (0 at shot t0, 1 at t1; outside in the handles)."""
        return self.t(frame) / self.dur if self.dur > 0 else 0.0

    # ---- misc helpers
    @property
    def w(self) -> int:
        return int(self.res[0])

    @property
    def h(self) -> int:
        return int(self.res[1])

    @property
    def portrait(self) -> bool:
        return self.res[1] > self.res[0]

    @property
    def preview(self) -> bool:
        return self.tier == "preview"

    def rng_for(self, key: str) -> random.Random:
        """An independent deterministic stream for ``key`` (stable regardless of call order elsewhere)."""
        import zlib
        return random.Random((self.seed * 1000003) ^ zlib.crc32(key.encode("utf-8")))

    def asset(self, name: str) -> dict[str, Any]:
        """The job asset ``name`` ({kind, path, frames_dir?, fps?, poster?}); KeyError lists the known names."""
        if name not in self.assets:
            raise KeyError(f"unknown asset {name!r} (job has: {', '.join(sorted(self.assets)) or 'none'})")
        return self.assets[name]

    def cue(self, t: float, sfx: str, gain_db: float = 0.0, align: str = "auto") -> None:
        """Register an audio cue at shot-local seconds ``t`` (merged into the film's cues)."""
        if not math.isfinite(float(t)):
            raise ValueError(f"cue {sfx!r}: t must be finite")
        self._cues.append({"t": round(float(t), 4), "sfx": str(sfx), "gain_db": float(gain_db), "align": align})


def from_job(job: dict[str, Any], schema: dict[str, Any] | None = None) -> SceneCtx:
    """SceneCtx from a parsed job.json (params resolved against the scene module's PARAMS schema)."""
    res = job.get("res") or [1920, 1080]
    assets = {str(k): dict(v) for k, v in (job.get("assets") or {}).items()}
    product_name = job.get("product")
    product = None
    if product_name:
        if product_name not in assets:
            raise ParamError(f"product asset {product_name!r} is not in the job's assets")
        product = {"name": product_name, **assets[product_name]}
    handles = job.get("handles") or [0.0, 0.0]
    return SceneCtx(
        params=resolve_params(schema, job.get("params")),
        fps=int(job.get("fps") or 30),
        dur=float(job["dur"]),
        frames=int(job["frame_count"]),
        res=(int(res[0]), int(res[1])),
        aspect=str(job.get("aspect") or ("9:16" if int(res[1]) > int(res[0]) else "16:9")),
        seed=int(job.get("seed") or 1),
        tier=str(job.get("tier") or "preview"),
        assets=assets,
        product=product,
        out_dir=Path(job["out_dir"]),
        handles=(float(handles[0]), float(handles[1])),
        handoff=dict(job["handoff"]) if job.get("handoff") else None,
        alpha=bool(job.get("alpha")),
        kit_root=Path(job["kit_root"]) if job.get("kit_root") else None,
        job=dict(job),
    )
