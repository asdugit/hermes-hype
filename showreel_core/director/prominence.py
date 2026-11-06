"""Product prominence: a static pre-render check of film.json, a pixel MEASUREMENT of the product in every
keyframe, and deterministic param bumps for kit scenes whose product reads too small.

Measurement (renderer-agnostic, works for 2D, WebGL and three.js scenes alike): the keyframes are rendered a
second time from a mirror of the page whose product media files are colour-flipped (every RGB value XOR 0x80,
alpha kept). Pixels that differ between the two renders are exactly where the product was drawn (after the
scene's own scaling, grading, palette quantisation and camera). The largest connected region gives the
product's on-screen width as a share of the frame width.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .checks import references

HERO_WIDTH = 0.25          # product width / frame width that reads as the hero
TARGET_WIDTH = 0.35        # what a prominence repair aims for
DIFF_THRESHOLD = 40        # per-channel difference (0-255) that counts as "the product was drawn here"
GRID_W = 192               # measurement grid (frame downsampled to GRID_W columns)
MIN_AREA = 0.0012          # smallest region (share of the frame) that counts as visible
MAX_BUMP = 2.6             # largest single size multiplier a repair applies

# Nature kit flyer slots (kits/nature/lib/flyers.js SLOTS: depth m, width m) and camera (world.js: vertical
# FOV 34 deg landscape / 58 deg portrait). Used only for the static estimate; the measurement is the truth.
NATURE_SLOTS = {"descend": (20, 5.4), "rise": (70, 6.0), "drive-slope": (26, 5.2), "float": (36, 6.0),
                "orbit": (44, 5.8), "arc": (90, 6.5), "cross": (52, 5.6), "hero": (16, 6.4)}
NATURE_DEFAULT_PATHS = ("descend", "rise", "drive-slope", "float", "arc", "orbit")
NATURE_FLYER_SCENES = ("kit:nature/flower-field", "kit:nature/sky-reveal")
NATURE_HERO_SCENES = ("kit:nature/product-hero",)
HERO_SIZE_M, HERO_DIST_M = 5.0, 19.0     # product-hero defaults (one product on the hilltop)
SCALE_PARAMS = ("product_scale", "productScale", "hero_scale")


@dataclass
class Measure:
    """The product in one keyframe (shares of the frame; 0 when not visible)."""
    cell: int
    shot: str
    t: float
    visible: bool = False
    width: float = 0.0
    height: float = 0.0
    area: float = 0.0
    bbox: tuple[float, float, float, float] | None = None     # x0, y0, x1, y1 as frame fractions
    regions: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------------------------ static check

def _tan_h(aspect: str) -> float:
    if aspect == "9:16":
        return math.tan(math.radians(58 / 2)) * 9 / 16
    return math.tan(math.radians(34 / 2)) * 16 / 9


def nature_flyers(params: dict[str, Any]) -> list[dict[str, Any]]:
    """The flyer specs a nature scene will fly (explicit ``flyers`` or the default squadron)."""
    fl = params.get("flyers")
    if isinstance(fl, list) and fl:
        return [f for f in fl if isinstance(f, dict)]
    prod = params.get("product")
    if not prod:
        return []
    try:
        n = int(params.get("count", 4))
    except (TypeError, ValueError):
        n = 4
    return [{"media": prod, "path": p} for p in NATURE_DEFAULT_PATHS[:max(0, min(n, 6))]]


def flyer_width(spec: dict[str, Any], aspect: str, scale: float = 1.0) -> float:
    """Estimated on-screen width share of one nature flyer at its slot depth."""
    path = str(spec.get("path") or "float")
    d0, s0 = NATURE_SLOTS.get(path, NATURE_SLOTS["float"])
    try:
        d = float(spec.get("d") or d0)
        size = float(spec.get("size") or s0) * scale
    except (TypeError, ValueError):
        d, size = d0, s0
    return size / max(0.5, 2 * d * _tan_h(aspect))


def estimate_width(shot: dict[str, Any], aspect: str) -> float | None:
    """Static estimate of the largest product width in a kit shot (None when the engine cannot estimate)."""
    scene, params = str(shot.get("scene", "")), shot.get("params") or {}
    scale = _scale_of(params)
    if scene in NATURE_FLYER_SCENES:
        ws = [flyer_width(f, aspect, scale) for f in nature_flyers(params)]
        return max(ws) if ws else 0.0
    if scene in NATURE_HERO_SCENES:
        fl = params.get("flyers")
        if isinstance(fl, list) and fl:
            return max(flyer_width({"path": "hero", **f}, aspect, scale) for f in fl if isinstance(f, dict))
        return _hero_width(params, aspect, scale)
    return None


def _hero_width(params: dict[str, Any], aspect: str, scale: float = 1.0) -> float:
    """product-hero without explicit flyers: ONE product of ``size`` m (default 5) on a hilltop ``distance`` m away
    (default 19) - kits/nature/kit.js."""
    try:
        size = float(params.get("size") or HERO_SIZE_M) * scale
        d = float(params.get("distance") or HERO_DIST_M)
    except (TypeError, ValueError):
        size, d = HERO_SIZE_M, HERO_DIST_M
    return size / max(0.5, 2 * d * _tan_h(aspect))


def _scale_of(params: dict[str, Any]) -> float:
    for k in SCALE_PARAMS:
        if k in params:
            try:
                return max(0.1, float(params[k]))
            except (TypeError, ValueError):
                return 1.0
    return 1.0


def static_check(film: dict[str, Any], plan: dict[str, Any], product: set[str], aspect: str
                 ) -> tuple[list[str], list[str]]:
    """Pre-render prominence rules: (errors for the model, notes). Product shots must reference the product
    media; kit shots whose product would read as a speck are listed (the engine bumps them, see :func:`bump`)."""
    errors: list[str] = []
    notes: list[str] = []
    if not product:
        return errors, notes
    intents = {p.get("id"): p for p in plan.get("shots") or [] if isinstance(p, dict)}
    for s in film.get("shots") or []:
        want = bool((intents.get(s["id"]) or {}).get("product_visible"))
        refs = references(s.get("params") or {}, product)
        if want and not refs:
            errors.append(f"shot `{s['id']}` is planned as product-visible but its params never reference the "
                          f"product media ({sorted(product)}): pass the asset name to the scene's media param")
        if refs:
            est = estimate_width(s, aspect)
            if est is not None and est < HERO_WIDTH:
                notes.append(f"shot `{s['id']}`: the largest product flyer would span ~{est:.0%} of the width")
    return errors, notes


# ------------------------------------------------------------------------------------ bumps

def bump(shot: dict[str, Any], factor: float, declared: Iterable[str] = ()) -> str:
    """Scale the product up in a kit shot by ``factor`` through its params. Returns what changed ('' = nothing
    the engine knows how to change; such shots go to the model as issues)."""
    factor = max(1.0, min(MAX_BUMP, factor))
    if factor < 1.05:
        return ""
    params = shot.setdefault("params", {})
    declared = set(declared)
    for k in SCALE_PARAMS:
        if k in declared or k in params:
            old = _scale_of(params)
            params[k] = round(min(3.0, old * factor), 2)
            return f"{k} {old:g} -> {params[k]:g}"
    scene = str(shot.get("scene", ""))
    if scene in NATURE_HERO_SCENES and not (isinstance(params.get("flyers"), list) and params["flyers"]):
        old = float(params.get("size") or HERO_SIZE_M)          # ONE hilltop product: grow it, never add flyers
        params["size"] = round(min(old * factor, 24.0), 2)
        return f"hero size {old:g} -> {params['size']:g} m"
    if scene in NATURE_FLYER_SCENES or scene in NATURE_HERO_SCENES:
        flyers = [dict(f) for f in nature_flyers(params)] or ([{"media": params.get("product"), "path": "hero"}]
                                                               if params.get("product") else [])
        if not flyers:
            return ""
        aspect = "16:9"
        ranked = sorted(range(len(flyers)), key=lambda i: -flyer_width(flyers[i], aspect))
        lead = ranked[0]
        changed = []
        for i, f in enumerate(flyers):
            path = str(f.get("path") or ("hero" if scene in NATURE_HERO_SCENES else "float"))
            base = float(f.get("size") or NATURE_SLOTS.get(path, NATURE_SLOTS["float"])[1])
            k = factor if i == lead else max(1.0, factor ** 0.5)       # the lead grows most; keep depth variety
            f["size"] = round(base * k, 2)
            changed.append(f"{path} {base:g}->{f['size']:g} m")
        params["flyers"] = flyers
        params.pop("count", None)
        return "flyer sizes " + ", ".join(changed)
    return ""


# ------------------------------------------------------------------------------------ measurement

def flip_image(src: Path, dst: Path) -> None:
    """Write ``src`` with every RGB value XOR 0x80 (alpha kept, same format) to ``dst``."""
    from PIL import Image

    lut = [v ^ 0x80 for v in range(256)]
    with Image.open(src) as im:
        im.load()
        mode = im.mode
        if mode in ("RGBA", "LA", "PA") or (mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            r, g, b, a = rgba.split()
            out = Image.merge("RGBA", (r.point(lut), g.point(lut), b.point(lut), a))
        else:
            out = im.convert("RGB").point(lut * 3)
        dst.parent.mkdir(parents=True, exist_ok=True)
        fmt = (im.format or "").upper() or ("PNG" if src.suffix.lower() == ".png" else "JPEG")
        if fmt in ("JPEG", "JPG") and out.mode == "RGBA":
            out = out.convert("RGB")
        kw: dict[str, Any] = {"quality": 92} if fmt in ("JPEG", "JPG") else {}
        out.save(dst, fmt if fmt != "JPG" else "JPEG", **kw)


_IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")


def flipped_assets(page_dir: Path, names: Iterable[str], cache_dir: Path) -> dict[str, Path]:
    """Colour-flipped copies of ``page_dir/assets/<name>/`` (cached by content signature). name -> dir."""
    out: dict[str, Path] = {}
    for name in names:
        src = page_dir / "assets" / name
        if not src.is_dir():
            continue
        files = sorted(p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in _IMG_EXT)
        if not files:
            continue
        listing = "|".join(f"{p.relative_to(src)}:{p.stat().st_size}" for p in files)
        sig = hashlib.sha1(listing.encode()).hexdigest()[:12]
        dst = cache_dir / f"{name}-{sig}"
        done = dst / ".done"
        if not done.is_file():
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)

            def one(p: Path, src: Path = src, dst: Path = dst) -> None:
                flip_image(p, dst / p.relative_to(src))
            with ThreadPoolExecutor(max_workers=4, thread_name_prefix="showreel-flip") as pool:
                list(pool.map(one, files))
            done.write_text("ok", encoding="utf-8")
        out[name] = dst
    return out


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def mirror_page(page_dir: Path, mask_dir: Path, flipped: dict[str, Path]) -> Path:
    """A copy of ``page_dir`` (hard links where possible) whose product asset files are the flipped ones."""
    if mask_dir.exists():
        shutil.rmtree(mask_dir, ignore_errors=True)
    for root, _dirs, files in os.walk(page_dir):
        rel = Path(root).relative_to(page_dir)
        (mask_dir / rel).mkdir(parents=True, exist_ok=True)
        for f in files:
            _link_or_copy(Path(root) / f, mask_dir / rel / f)
    for name, src in flipped.items():
        for p in src.rglob("*"):
            if p.is_file() and p.name != ".done":
                dst = mask_dir / "assets" / name / p.relative_to(src)
                if dst.exists():
                    dst.unlink()                     # never write through a hard link into the real page
                dst.parent.mkdir(parents=True, exist_ok=True)
                _link_or_copy(p, dst)
    return mask_dir


def measure(normal: bytes, flipped: bytes, *, threshold: int = DIFF_THRESHOLD, grid_w: int = GRID_W,
            min_area: float = MIN_AREA,
            ) -> tuple[bool, float, float, float, tuple[float, float, float, float] | None, int]:
    """(visible, width, height, area, bbox, regions) of the product from a normal/flipped keyframe pair."""
    from PIL import Image, ImageChops

    a = Image.open(io.BytesIO(normal)).convert("RGB")
    b = Image.open(io.BytesIO(flipped)).convert("RGB")
    if b.size != a.size:
        b = b.resize(a.size)
    diff = ImageChops.difference(a, b)
    r, g, bl = diff.split()
    mx = ImageChops.lighter(ImageChops.lighter(r, g), bl)
    gw = max(16, min(grid_w, a.width))
    gh = max(9, round(gw * a.height / a.width))
    small = mx.point([255 if v >= threshold else 0 for v in range(256)]).resize((gw, gh), Image.Resampling.BOX)
    on = [int(v) >= 64 for v in small.tobytes()]     # >= 25 % of the cell's pixels changed
    seen = [False] * len(on)
    best: tuple[int, int, int, int, int] | None = None     # area, x0, y0, x1, y1
    regions = 0
    min_cells = max(2, round(min_area * gw * gh))
    for start, flag in enumerate(on):
        if not flag or seen[start]:
            continue
        stack = [start]
        seen[start] = True
        n, x0, y0, x1, y1 = 0, gw, gh, -1, -1
        while stack:
            i = stack.pop()
            n += 1
            x, y = i % gw, i // gw
            x0, x1, y0, y1 = min(x0, x), max(x1, x), min(y0, y), max(y1, y)
            for dy in (-1, 0, 1):
                yy = y + dy
                if yy < 0 or yy >= gh:
                    continue
                for dx in (-1, 0, 1):
                    xx = x + dx
                    if 0 <= xx < gw:
                        j = yy * gw + xx
                        if on[j] and not seen[j]:
                            seen[j] = True
                            stack.append(j)
        if n >= min_cells:
            regions += 1
            if best is None or n > best[0]:
                best = (n, x0, y0, x1, y1)
    if best is None:
        return False, 0.0, 0.0, 0.0, None, 0
    n, x0, y0, x1, y1 = best
    bbox = (round(x0 / gw, 3), round(y0 / gh, 3), round((x1 + 1) / gw, 3), round((y1 + 1) / gh, 3))
    return True, round(bbox[2] - bbox[0], 3), round(bbox[3] - bbox[1], 3), round(n / (gw * gh), 4), bbox, regions


def measure_frames(frames: list[Any], normal: list[bytes], flipped: list[bytes]) -> list[Measure]:
    """One :class:`Measure` per keyframe (``frames`` are sheet.Frame objects)."""
    out = []
    for f, a, b in zip(frames, normal, flipped, strict=False):
        try:
            vis, w, h, area, bbox, regions = measure(a, b)
        except Exception:
            vis, w, h, area, bbox, regions = False, 0.0, 0.0, 0.0, None, 0
        out.append(Measure(f.cell, f.shot, f.t, vis, w, h, area, bbox, regions))
    return out


@dataclass
class Prominence:
    """Film-level summary of the measurements."""
    visible_share: float
    hero_share: float
    per_shot: dict[str, dict[str, float]]          # shot -> {max_width, visible, frames}
    hook_visible: bool | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def summarise(measures: list[Measure], hook_t: float = 1.0) -> Prominence:
    """Visible share, hero share (width >= HERO_WIDTH) and per-shot maxima."""
    if not measures:
        return Prominence(0.0, 0.0, {}, None)
    per: dict[str, dict[str, float]] = {}
    for m in measures:
        d = per.setdefault(m.shot, {"max_width": 0.0, "visible": 0.0, "frames": 0.0})
        d["frames"] += 1
        d["visible"] += 1 if m.visible else 0
        d["max_width"] = max(d["max_width"], m.width if m.visible else 0.0)
    for d in per.values():
        d["visible"] = round(d["visible"] / d["frames"], 3)
    hook = min(measures, key=lambda m: abs(m.t - hook_t))
    return Prominence(round(sum(m.visible for m in measures) / len(measures), 3),
                      round(sum(m.visible and m.width >= HERO_WIDTH for m in measures) / len(measures), 3),
                      per, hook.visible if abs(hook.t - hook_t) < 0.6 else None)


def facts(p: Prominence, film: dict[str, Any], measures: list[Measure] | None = None) -> list[str]:
    """Engine-measured facts for the critic and the revisions."""
    lines = [f"MEASURED (pixel-exact): the product is visible in {p.visible_share:.0%} of keyframes and spans "
             f">= {HERO_WIDTH:.0%} of the frame width in {p.hero_share:.0%}"]
    order = [s["id"] for s in film.get("shots") or []]
    parts = [f"{sid} {p.per_shot[sid]['max_width']:.0%}" for sid in order if sid in p.per_shot]
    if parts:
        lines.append("MEASURED largest product width per shot: " + ", ".join(parts))
    if p.hook_visible is False:
        lines.append("MEASURED: the product is not on screen at the 1 s hook frame")
    crops = cropped(measures or [])
    if crops:
        lines.append("MEASURED: the product runs off the frame edge in " + ", ".join(
            f"{sid} ({'/'.join(sorted(edges))}, {n} frame(s))" for sid, (edges, n) in crops.items())
            + " - fine for a deliberate UI close-up, a flaw for a hero or flying product")
    return lines


def cropped(measures: list[Measure], edge: float = 0.006) -> dict[str, tuple[set[str], int]]:
    """Shots whose (non-trivial) product region touches a frame edge: shot -> (edges, frames)."""
    out: dict[str, tuple[set[str], int]] = {}
    for m in measures:
        if not m.visible or m.bbox is None or m.width < 0.12:
            continue
        x0, y0, x1, y1 = m.bbox
        edges = {k for k, hit in (("left", x0 <= edge), ("top", y0 <= edge), ("right", x1 >= 1 - edge),
                                  ("bottom", y1 >= 1 - edge)) if hit}
        if edges:
            prev = out.get(m.shot, (set(), 0))
            out[m.shot] = (prev[0] | edges, prev[1] + 1)
    return out


def save(path: Path, measures: list[Measure], summary: Prominence) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"summary": summary.to_dict(), "frames": [m.to_dict() for m in measures]}, indent=1),
                    encoding="utf-8")
