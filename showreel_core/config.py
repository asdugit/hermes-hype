"""Film options, plugin settings (``config_schema``) and style discovery. Stdlib only.

``Options`` is what one film is made with; it is persisted in ``job.json`` (SPEC 3.8) and
shared by the slash command, the agent tools, the CLI and the Desktop pane. ``Settings`` are
the user's defaults from ``plugins.entries.showreel.settings`` (see ``plugin.yaml``).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .contracts import MODE_ALIASES

MODES = ("product", "making_of", "speedrun")
EFFORTS = ("quick", "standard", "max")
#: Output sizes per aspect: final (1080p30) and preview (540p15) presets (SPEC 4).
ASPECT_SIZES: dict[str, tuple[int, int]] = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
PREVIEW_SIZES: dict[str, tuple[int, int]] = {"16:9": (960, 540), "9:16": (540, 960), "1:1": (540, 540)}
FINAL_FPS, PREVIEW_FPS = 30, 15
MIN_SECONDS, MAX_SECONDS = 15, 180
DEFAULT_STYLE = "launch"
#: Styles every build knows by name (audio beds + story tones exist for them).
BUILTIN_STYLES = ("launch", "pixel", "terminal", "blueprint", "cinematic")
#: Narration pace per style, passed to Hermes ``text_to_speech`` as ``speed`` (never a post-synthesis stretch).
#: A style pack may declare its own ``voice_speed``; the ``narration_speed`` setting overrides both.
#: cinematic: locked by the user's ear test at 1.13 (Edge rate +13%, ~176 wpm with en-US-AndrewMultilingualNeural).
STYLE_VOICE_SPEED: dict[str, float] = {"cinematic": 1.13}
VOICE_SPEED_RANGE = (0.25, 4.0)

REPO_ROOT = Path(__file__).resolve().parents[1]


def clamp_seconds(value: Any, default: int = 60) -> int:
    """Film length in whole seconds, clamped to 15..180 (bad input -> ``default``)."""
    try:
        secs = round(float(value))
    except (TypeError, ValueError):
        secs = default
    return max(MIN_SECONDS, min(MAX_SECONDS, secs))


def norm_speed(value: Any) -> float | None:
    """A TTS speed in 0.25..4.0, or ``None`` for empty/invalid input (= use the style's pace)."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    lo, hi = VOICE_SPEED_RANGE
    return round(min(hi, max(lo, v)), 3) if v > 0 else None


def norm_mode(value: Any) -> str:
    """Film mode from a command word or alias (``lore`` -> ``making_of``); unknown -> ``product``."""
    key = str(value or "").strip().lower()
    return MODE_ALIASES.get(key, key if key in MODES else "product")


ENGINES_3D = ("browser", "blender", "auto")


def norm_engine(value: Any) -> str:
    """``engine_3d`` value: browser (three.js, default) | blender | auto (Blender when installed)."""
    key = str(value or "").strip().lower()
    key = {"three": "browser", "threejs": "browser", "three.js": "browser", "chromium": "browser"}.get(key, key)
    return key if key in ENGINES_3D else "browser"


def norm_aspects(value: Any) -> list[str]:
    """``"both"``/``"vertical"``/``["16:9","9:16"]``/... -> ordered unique aspect list (default 16:9)."""
    raw = value if isinstance(value, (list, tuple)) else [value]
    out: list[str] = []
    for item in raw:
        key = str(item or "").strip().lower()
        picked = {"both": ["16:9", "9:16"], "vertical": ["9:16"], "portrait": ["9:16"], "9:16": ["9:16"],
                  "horizontal": ["16:9"], "landscape": ["16:9"], "16:9": ["16:9"], "wide": ["16:9"],
                  "square": ["1:1"], "1:1": ["1:1"]}.get(key, [])
        out += [a for a in picked if a not in out]
    return out or ["16:9"]


@dataclass
class Options:
    """How one film is made (persisted as ``job.options``)."""
    mode: str = "product"                  # product | making_of | speedrun
    style: str = DEFAULT_STYLE
    seconds: int = 60
    aspects: list[str] = field(default_factory=lambda: ["16:9"])
    voice: bool = True                     # False -> captions only
    effort: str = "standard"               # Director budget: quick | standard | max
    preview: bool = False                  # 540p15 preview preset
    redact: bool = True
    direction: str = ""                    # free text -> Directed mode
    notes: str = ""                        # /showreel revise <notes>
    brief: dict[str, Any] = field(default_factory=dict)   # agent product brief {name, url, one_liner, features}
    workers: int | None = None             # max parallel render workers (None = auto)
    voice_speed: float | None = None       # narration pace override (None = the style's voice_speed)
    hints: dict[str, Any] = field(default_factory=dict)   # parse hints for the Director (style words in text...)
    explicit: list[str] = field(default_factory=list)     # option names the user set explicitly
    engine_3d: str = "browser"             # 3D shots: browser (three.js) | blender (user's Blender) | auto
    blender_path: str = ""                 # explicit Blender executable (else SHOWREEL_BLENDER / PATH / standard)

    @property
    def directed(self) -> bool:
        return bool(self.direction.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Options:
        """Tolerant inverse of :meth:`to_dict` (unknown keys ignored, values normalised)."""
        data = dict(data or {})
        known = {f.name for f in fields(cls)}
        opts = cls(**{k: v for k, v in data.items() if k in known})
        return opts.normalised()

    def normalised(self) -> Options:
        """Copy with every field coerced into its valid range."""
        o = Options(**{f.name: getattr(self, f.name) for f in fields(self)})
        o.mode = norm_mode(o.mode)
        o.style = str(o.style or DEFAULT_STYLE).strip().lower() or DEFAULT_STYLE
        o.seconds = clamp_seconds(o.seconds)
        o.aspects = norm_aspects(o.aspects)
        o.voice = bool(o.voice)
        o.effort = o.effort if o.effort in EFFORTS else "standard"
        o.preview, o.redact = bool(o.preview), bool(o.redact)
        o.direction, o.notes = str(o.direction or "").strip(), str(o.notes or "").strip()
        o.brief = dict(o.brief) if isinstance(o.brief, dict) else {}
        try:
            o.workers = max(1, min(8, int(o.workers))) if o.workers not in (None, "", 0) else None
        except (TypeError, ValueError):
            o.workers = None
        o.voice_speed = norm_speed(o.voice_speed)
        o.hints = dict(o.hints) if isinstance(o.hints, dict) else {}
        o.explicit = [str(x) for x in (o.explicit or [])]
        o.engine_3d = norm_engine(o.engine_3d)
        o.blender_path = str(o.blender_path or "").strip()
        return o


@dataclass
class Settings:
    """User defaults from ``config_schema`` (``plugins.entries.showreel.settings.*``)."""
    default_style: str = DEFAULT_STYLE
    default_seconds: int = 60
    aspect: str = "16:9"                   # 16:9 | 9:16 | both | 1:1
    narration: bool = True
    redact: bool = True
    effort: str = "standard"
    max_parallel_workers: int = 0          # 0 = auto
    narration_speed: float | None = None   # empty = each style's voice_speed
    engine_3d: str = "browser"             # browser | blender | auto
    blender_path: str = ""                 # path to the blender executable (optional)

    def options(self) -> Options:
        """Default :class:`Options` for a new film."""
        return Options(style=self.default_style, seconds=self.default_seconds, aspects=norm_aspects(self.aspect),
                       voice=self.narration, redact=self.redact, effort=self.effort,
                       workers=self.max_parallel_workers or None,
                       voice_speed=norm_speed(self.narration_speed), engine_3d=self.engine_3d,
                       blender_path=self.blender_path).normalised()


def load_settings(get_config: Callable[[str, Any], Any] | None = None) -> Settings:
    """Read settings through ``ctx.get_config`` (missing/broken values fall back to defaults)."""
    s = Settings()
    if get_config is None:
        return s
    for f in fields(Settings):
        try:
            val = get_config(f.name, getattr(s, f.name))
        except Exception:  # noqa: BLE001, S112 - a bad config file must never break the plugin
            continue
        if val is None:
            continue
        current = getattr(s, f.name)
        if f.name == "narration_speed":
            s.narration_speed = norm_speed(val)
            continue
        try:
            if isinstance(current, bool):
                val = val if isinstance(val, bool) else str(val).strip().lower() in ("1", "true", "yes", "on")
            setattr(s, f.name, type(current)(val))
        except (TypeError, ValueError):
            continue
    return s


def settings_from_hermes_config() -> Settings:
    """Settings without a plugin ``ctx`` (dashboard API): ``plugins.entries.showreel.settings`` in config.yaml.

    Read-only; defaults when not inside Hermes or the file cannot be read.
    """
    try:
        import yaml  # Hermes core dependency
        from hermes_constants import get_hermes_home  # public, lazy
        raw = yaml.safe_load((Path(get_hermes_home()) / "config.yaml").read_text(encoding="utf-8")) or {}
        entry = ((raw.get("plugins") or {}).get("entries") or {}).get("showreel") or {}
        values = entry.get("settings") or entry.get("config") or {}
    except Exception:  # noqa: BLE001
        return Settings()
    if not isinstance(values, dict):
        return Settings()
    return load_settings(lambda key, default: values.get(key, default))


# --------------------------------------------------------------------------- styles

@dataclass
class StyleInfo:
    """A style the user can ask for. ``ready`` = a kit/style pack exists in this build."""
    id: str
    name: str = ""
    blurb: str = ""
    ready: bool = False
    source: str = ""                       # "kit:<kit>" | "styles/<id>" | "builtin"
    preview: str = ""                      # absolute path of a preview image/video, if shipped
    voice_speed: float = 1.0               # narration pace for this style (TTS ``speed``)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_BLURBS = {
    "launch": "Premium product-launch motion graphics",
    "pixel": "16-bit arcade: pixel art, chiptune, quest log",
    "terminal": "Phosphor CRT terminal with scanlines",
    "blueprint": "Engineering drawing, line art drawn on",
    "cinematic": "Captures as lit cards in dark 3D space",
}


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _preview(folder: Path) -> str:
    for name in ("preview.webp", "preview.png", "preview.jpg", "preview.mp4"):
        if (folder / name).is_file():
            return str(folder / name)
    return ""


def _kit_styles(kit_dir: Path) -> list[dict[str, Any]]:
    """Style declarations of one kit: ``kit.json`` ``style`` (object) / ``styles`` (list), or ``style.json``."""
    out: list[dict[str, Any]] = []
    meta = _read_json(kit_dir / "kit.json")
    decl = meta.get("styles", meta.get("style"))
    for item in decl if isinstance(decl, list) else [decl] if decl else []:
        if isinstance(item, str):
            out.append({"id": item})
        elif isinstance(item, dict) and item.get("id"):
            out.append(item)
    if (kit_dir / "style.json").is_file():
        sj = _read_json(kit_dir / "style.json")
        if sj.get("id"):
            out.append(sj)
    return out


def discover_styles(root: Path | None = None) -> dict[str, StyleInfo]:
    """All style ids: kits that define a style, ``styles/<id>/style.json`` packs, and the built-in names.

    Built-in names are always accepted (``ready`` tells whether this build can render them yet);
    the pipeline falls back to ``launch`` for a style that cannot be built.
    """
    root = root or REPO_ROOT
    found: dict[str, StyleInfo] = {}
    for kit_dir in sorted((root / "kits").glob("*")) if (root / "kits").is_dir() else []:
        if not kit_dir.is_dir():
            continue
        for decl in _kit_styles(kit_dir):
            sid = str(decl["id"]).strip().lower()
            found.setdefault(sid, StyleInfo(sid, str(decl.get("name") or sid.title()),
                                            str(decl.get("blurb") or _BLURBS.get(sid, "")), True,
                                            f"kit:{kit_dir.name}", _preview(kit_dir), _declared_speed(decl, sid)))
    for sdir in sorted((root / "styles").glob("*")) if (root / "styles").is_dir() else []:
        meta = _read_json(sdir / "style.json")
        if not meta:
            continue
        sid = str(meta.get("id") or sdir.name).strip().lower()
        found.setdefault(sid, StyleInfo(sid, str(meta.get("name") or sid.title()),
                                        str(meta.get("blurb") or _BLURBS.get(sid, "")), True,
                                        f"styles/{sdir.name}", _preview(sdir), _declared_speed(meta, sid)))
    for sid in BUILTIN_STYLES:
        kit_dir = root / "kits" / sid
        if sid not in found and (kit_dir / "kit.js").is_file():
            # A kit named after a built-in style IS that style, even when its kit.json predates the
            # ``style`` declaration (launch, pixel, cinematic): film/quick.py renders it by that name.
            meta = _read_json(kit_dir / "kit.json")
            found[sid] = StyleInfo(sid, sid.title(), _BLURBS.get(sid, "") or str(meta.get("describe") or ""), True,
                                   f"kit:{sid}", _preview(kit_dir), STYLE_VOICE_SPEED.get(sid, 1.0))
        found.setdefault(sid, StyleInfo(sid, sid.title(), _BLURBS.get(sid, ""), False, "builtin",
                                        voice_speed=STYLE_VOICE_SPEED.get(sid, 1.0)))
    return found


def _declared_speed(decl: dict[str, Any], sid: str) -> float:
    """``voice_speed`` (or ``voice: {speed}``) from a style declaration, else the built-in table."""
    voice = decl.get("voice") if isinstance(decl.get("voice"), dict) else {}
    return norm_speed(decl.get("voice_speed", voice.get("speed"))) or STYLE_VOICE_SPEED.get(sid, 1.0)


def voice_speed(style: str, override: Any = None, root: Path | None = None) -> float:
    """Narration pace for ``style``: the ``narration_speed`` override if set, else the style's ``voice_speed``."""
    forced = norm_speed(override)
    if forced is not None:
        return forced
    info = discover_styles(root).get(str(style or "").lower())
    return info.voice_speed if info is not None else STYLE_VOICE_SPEED.get(str(style or "").lower(), 1.0)


def style_ids(root: Path | None = None) -> list[str]:
    """Every accepted style id (ready ones first, then built-in names)."""
    styles = discover_styles(root)
    return sorted(styles, key=lambda s: (not styles[s].ready, s))
