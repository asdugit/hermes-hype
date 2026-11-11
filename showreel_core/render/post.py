"""Named ffmpeg post-processing chains applied inside the per-chunk encode (no extra pass).

A chain spec is one name or several joined with ``+`` (e.g. ``"bloom+grain_vignette"``).
Stage order is fixed regardless of the spec order:

1. decode JPEG (full-range BT.601) -> planar RGB
2. ``pixel``: fixed palette (``paletteuse dither=none``) at the internal size
3. resize to the output size (nearest-neighbour for ``pixel``, lanczos otherwise)
4. RGB effects at output size: ``grade`` (mood: mono / one held colour / contrast / tint / chroma shift / tracking
   wobble), ``bloom``; ``crt`` glow
5. one static multiply mask (vignette and/or CRT scanlines), then CRT curvature
6. -> yuv420p BT.709 limited range, then seeded luma grain (``grain_vignette``)

The mask is a Pillow-generated greyscale PNG decoded once and repeated with the ``loop`` filter:
~1.3 ms/frame at 1080p versus ~10.5 ms for ``drawgrid`` + ``vignette`` (both single-threaded).
Every random source is seeded (``noise`` gets an explicit seed; its default -1 is random).
"""
from __future__ import annotations

import math
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import RenderError

POST_CHAINS = ("none", "grain_vignette", "pixel", "crt", "bloom", "grade")

DEFAULTS: dict[str, dict[str, Any]] = {
    # vignette = darkening at the frame corners (0..1); grain = ffmpeg noise strength on luma
    "grain_vignette": {"grain": 7, "vignette": 0.35},
    "pixel": {"palette": None},
    # scanline = darkening of every period-th row; period None -> round(out_h / 360) (3 px at 1080p)
    "crt": {"glow": 0.35, "scanline": 0.30, "period": None, "curvature": 0.05, "vignette": 0.45},
    "bloom": {"threshold": 222, "amount": 0.55, "sigma": 6.0},
    # mood grade (the Director's per-direction look over every scene AND the product media):
    # mono 0..1 desaturation; hold = "#hex" keeps that one colour while the rest goes to black and white (noir);
    # contrast 1 = unchanged (S-curve); tint = "#hex" multiplied in at tint_amount; shift = px of red/blue
    # misregistration (VHS chroma bleed); wobble = px of horizontal tracking sway; smear = horizontal-only blur sigma
    # (tape softness); band = opacity of the head-switching noise band along the bottom (VHS); rain 0..1 (noir).
    # hold_mode "hue" (default) keeps only pixels within +-hold_width degrees of the held colour's hue AND with real
    # chroma (a car's red survives, pink/yellow/orange flowers and skin go grey); "rgb" = ffmpeg colorhold by RGB
    # distance (hold_similarity/hold_blend), which kept pink and yellow flowers next to a warm red in a real film
    "grade": {"mono": 0.0, "hold": None, "hold_mode": "hue", "hold_width": 12.0, "hold_similarity": 0.22,
              "hold_blend": 0.12, "saturation": 1.0, "contrast": 1.0,
              "tint": None, "tint_amount": 0.0, "shift": 0, "wobble": 0, "rain": 0.0, "smear": 0.0, "band": 0.0},
}

# Filters each chain needs (checked against the ffmpeg capability probe).
REQUIRED_FILTERS: dict[str, tuple[str, ...]] = {
    "none": ("scale", "format"),
    "grain_vignette": ("blend", "loop", "noise"),
    "pixel": ("paletteuse",),
    "crt": ("split", "gblur", "blend", "loop", "lenscorrection"),
    "bloom": ("split", "lutrgb", "gblur", "blend"),
    "grade": ("colorchannelmixer", "curves", "colorhold", "rgbashift", "crop", "overlay", "loop", "gblur",
              "drawbox", "extractplanes", "lut2", "maskedmerge"),
}


@dataclass(frozen=True)
class PostChain:
    """A ready ``-filter_complex`` graph (input ``[0:v]`` -> output ``[vout]``)."""
    spec: str
    graph: str
    extra_inputs: tuple[str, ...] = field(default_factory=tuple)
    required_filters: tuple[str, ...] = field(default_factory=tuple)


def chain_seed(seed: int, chunk_index: int) -> int:
    """Deterministic non-negative noise seed per (job seed, chunk) via crc32."""
    return zlib.crc32(f"{seed}:{chunk_index}".encode()) & 0x7FFFFFFF


def parse_spec(spec: str | None) -> list[str]:
    """Split ``"a+b"`` into validated chain names (``none`` dropped unless alone)."""
    names = [n.strip() for n in (spec or "none").split("+") if n.strip()]
    bad = [n for n in names if n not in POST_CHAINS]
    if bad:
        raise RenderError("post", f"unknown post chain(s) {bad}", hint=f"choose from {POST_CHAINS}")
    return list(dict.fromkeys(n for n in names if n != "none"))


def _hex(c: str) -> tuple[int, int, int]:
    s = c.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        raise RenderError("post", f"bad palette colour {c!r}")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def write_palette_png(colors: list[str], path: Path) -> Path:
    """Write a 16x16 palette image (paletteuse wants exactly 256 entries; the last colour pads)."""
    from PIL import Image

    rgb = [_hex(c) for c in colors][:256]
    if not rgb:
        raise RenderError("post", "pixel palette is empty")
    rgb += [rgb[-1]] * (256 - len(rgb))
    img = Image.new("RGB", (16, 16))
    img.putdata(rgb)
    img.save(path, "PNG")
    return path


def write_mask_png(size: tuple[int, int], path: Path, *, vignette: float = 0.0, scanline: float = 0.0,
                   period: int = 3) -> Path:
    """Greyscale multiply mask: radial vignette (corners -> 1-vignette) x dark every ``period``-th row."""
    from PIL import Image, ImageChops

    w, h = size
    # Image.radial_gradient: 256x256, 0 at the centre -> 255 at radius 128 (corners ~181).
    rad = Image.radial_gradient("L").resize((w, h), Image.Resampling.BILINEAR)
    corner = 181.0
    lut = [int(round(255 * (1.0 - vignette * min(1.0, d / corner) ** 2.2))) for d in range(256)]
    mask = rad.point(lut)
    if scanline > 0 and period >= 2:
        col = Image.new("L", (1, period), 255)
        col.putpixel((0, period - 1), int(round(255 * (1.0 - scanline))))
        lines = Image.new("L", (w, h))
        strip = col.resize((w, period), Image.Resampling.NEAREST)
        for y in range(0, h, period):
            lines.paste(strip, (0, y))
        mask = ImageChops.multiply(mask, lines)
    mask.save(path, "PNG")
    return path


def write_rain_png(size: tuple[int, int], path: Path, *, density: float = 0.5, seed: int = 0) -> Path:
    """Transparent RGBA texture of thin, slightly slanted light streaks (the noir mood's rain), seeded."""
    import random

    from PIL import Image, ImageDraw

    w, h = size                          # h = 2 x frame height; the bottom half repeats the top (seamless loop)
    rnd = random.Random(seed)
    half = Image.new("RGBA", (w, h // 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(half)
    for _ in range(int(450 * density * (w * h) / (1920 * 2160))):
        x, y = rnd.uniform(0, w), rnd.uniform(-0.06 * h, h // 2)
        ln = rnd.uniform(0.025, 0.06) * h
        a = int(rnd.uniform(28, 80) * (0.6 + 0.4 * density))
        d.line([(x, y), (x - ln * 0.18, y + ln)], fill=(225, 230, 240, a), width=1 if rnd.random() < 0.7 else 2)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    img.paste(half, (0, 0))
    img.paste(half, (0, h // 2))
    img.save(path, "PNG")
    return path


class _Graph:
    """Tiny filter-graph builder: a running linear chain plus labelled side branches."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.cur = "0:v"
        self.pending: list[str] = []
        self.n = 0
        self.inputs = 1          # next free ffmpeg input index

    def label(self) -> str:
        self.n += 1
        return f"s{self.n}"

    def add(self, *filters: str) -> None:
        self.pending.extend(filters)

    def flush(self) -> str:
        out = self.label()
        self.parts.append(f"[{self.cur}]{','.join(self.pending) or 'null'}[{out}]")
        self.pending, self.cur = [], out
        return out

    def split(self) -> tuple[str, str]:
        a, b = self.label(), self.label()
        self.parts.append(f"[{self.cur}]{','.join([*self.pending, 'split'])}[{a}][{b}]")
        self.pending = []
        return a, b

    def branch(self, src: str, filters: list[str]) -> str:
        out = self.label()
        self.parts.append(f"[{src}]{','.join(filters)}[{out}]")
        return out

    def join(self, a: str, b: str, flt: str) -> None:
        self.cur = self.label()
        self.parts.append(f"[{a}][{b}]{flt}[{self.cur}]")

    def text(self) -> str:
        self.parts.append(f"[{self.cur}]{','.join(self.pending) or 'null'}[vout]")
        return ";".join(self.parts)


def _p(name: str, params: Mapping[str, Mapping[str, Any]] | None) -> dict[str, Any]:
    out = dict(DEFAULTS.get(name, {}))
    out.update({k: v for k, v in (params or {}).get(name, {}).items() if v is not None})
    return out


def build_post(spec: str | None, *, in_size: tuple[int, int], out_size: tuple[int, int], seed: int = 0,
               params: Mapping[str, Mapping[str, Any]] | None = None, work_dir: Path | None = None,
               image_codec: str = "mjpeg") -> PostChain:
    """Build the ``-filter_complex`` graph for ``spec``.

    ``params`` maps chain name -> overrides of :data:`DEFAULTS` (e.g. ``{"pixel": {"palette": [...]}}``).
    ``seed`` should already be per chunk (:func:`chain_seed`). ``work_dir`` receives the palette and
    mask PNGs (required by ``pixel`` with a palette, ``grain_vignette`` and ``crt``).
    """
    names = parse_spec(spec)
    (iw, ih), (ow, oh) = in_size, out_size
    g = _Graph()
    extra: list[str] = []
    required = list(REQUIRED_FILTERS["none"])
    for n in names:
        required += REQUIRED_FILTERS[n]

    def need_dir() -> Path:
        if work_dir is None:
            raise RenderError("post", f"post chain {spec!r} needs a work_dir")
        work_dir.mkdir(parents=True, exist_ok=True)
        return work_dir

    # 1. decode -> planar RGB. Chrome JPEGs are JFIF: full range, BT.601 matrix.
    g.add("scale=in_range=pc:in_color_matrix=bt601" if image_codec == "mjpeg" else "scale", "format=gbrp")

    # 2. pixel palette at the internal size
    pixel = "pixel" in names
    palette = _p("pixel", params).get("palette") if pixel else None
    if palette:
        png = write_palette_png(list(palette), need_dir() / "palette.png")
        extra += ["-i", str(png)]
        g.add("format=rgb24")
        src = g.flush()
        g.join(src, f"{g.inputs}:v", "paletteuse=dither=none:new=0")
        g.inputs += 1
        g.add("format=gbrp")

    # 3. resize to output
    if (iw, ih) != (ow, oh):
        g.add(f"scale={ow}:{oh}:flags={'neighbor' if pixel else 'lanczos'}", "format=gbrp")

    # 4. RGB effects at output size (glows computed at quarter resolution)
    small = f"scale={max(2, ow // 4)}:{max(2, oh // 4)}:flags=area"
    big = f"scale={ow}:{oh}:flags=bilinear"
    if "grade" in names:
        gp = _p("grade", params)
        _grade(g, gp, ow, oh)
        rain = max(0.0, min(1.0, float(gp.get("rain") or 0.0)))
        if rain > 0:                      # a seeded streak texture, looped and scrolled down-left per frame
            rpath = need_dir() / f"rain_{ow}x{oh}_{rain:g}_{seed % 7}.png"
            if not rpath.exists():
                write_rain_png((ow, oh * 2), rpath, density=rain, seed=seed % 7)
            extra += ["-i", str(rpath)]
            src = g.flush()
            rn = g.branch(f"{g.inputs}:v", ["format=gbrap", "loop=loop=-1:size=1:start=0"])
            g.inputs += 1
            g.join(src, rn, f"overlay=x=0:y='mod(n*61\\,{oh})-{oh}':shortest=1:format=gbrp")
    if "bloom" in names:
        b = _p("bloom", params)
        thr = int(b["threshold"])
        lut = f"clip((val-{thr})*{255.0 / max(1, 255 - thr):.4f}\\,0\\,255)"
        a, c = g.split()
        glow = g.branch(c, [small, f"lutrgb=r='{lut}':g='{lut}':b='{lut}'",
                            f"gblur=sigma={float(b['sigma']):g}", big])
        g.join(a, glow, f"blend=all_mode=screen:all_opacity={float(b['amount']):g}")
    crt = _p("crt", params) if "crt" in names else None
    if crt:
        a, c = g.split()
        glow = g.branch(c, [small, "gblur=sigma=3", big])
        g.join(a, glow, f"blend=all_mode=screen:all_opacity={float(crt['glow']):g}")

    # 5. static multiply mask (vignette x scanlines), then curvature
    vig = max(float(crt["vignette"]) if crt else 0.0,
              float(_p("grain_vignette", params)["vignette"]) if "grain_vignette" in names else 0.0)
    scan = float(crt["scanline"]) if crt else 0.0
    if vig > 0 or scan > 0:
        period = int(crt["period"] or max(2, round(oh / 360))) if crt else 3
        mpath = need_dir() / f"mask_{ow}x{oh}_{vig:g}_{scan:g}_{period}.png"
        if not mpath.exists():
            write_mask_png((ow, oh), mpath, vignette=vig, scanline=scan, period=period)
        extra += ["-i", str(mpath)]
        src = g.flush()
        mk = g.branch(f"{g.inputs}:v", ["format=gbrp", "loop=loop=-1:size=1:start=0"])
        g.inputs += 1
        g.join(src, mk, "blend=all_mode=multiply:shortest=1")
    if crt and float(crt["curvature"]):
        k = float(crt["curvature"])
        g.add(f"lenscorrection=k1={k:g}:k2={k / 2:g}:i=bilinear")

    # 6. -> yuv420p BT.709 limited range, then luma grain. setparams is required: ffmpeg >= 7 takes
    # colour tags from the filtered frames, which override -color_primaries/-color_trc (measured:
    # without it the stream is tagged "bt709/unknown/unknown", the FiverrAds symptom).
    g.add("scale=out_range=tv:out_color_matrix=bt709", "format=yuv420p")
    if "grain_vignette" in names:
        gv = _p("grain_vignette", params)
        g.add(f"noise=c0_seed={int(seed) & 0x7FFFFFFF}:c0_strength={int(gv['grain'])}:c0_flags=t+u")
    g.add("setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")

    return PostChain(spec or "none", g.text(), tuple(extra), tuple(dict.fromkeys(required)))


def hue_mask_expr(hold: str, width_deg: float = 12.0, soft_deg: float = 6.0, chroma_floor: float = 24.0,
                  chroma_soft: float = 14.0) -> str:
    """lut2 expression over (x = Cb, y = Cr) -> 0..255: 255 within +-``width_deg`` of ``hold``'s hue angle in the
    Cb/Cr plane (soft edge ``soft_deg``) AND with chroma above ``chroma_floor`` (so pale pinks and greys never
    count). BT.601 limited-range coefficients, like the RGB->YUV conversion in front of it."""
    r, g, b = _hex(hold)
    du = (-37.797 * r - 74.203 * g + 112.0 * b) / 255.0
    dv = (112.0 * r - 93.786 * g - 18.214 * b) / 255.0
    a = math.atan2(dv, du)
    w, sf = math.radians(width_deg), math.radians(max(1.0, soft_deg))
    ang = rf"abs(atan2(y-128\,x-128)-({a:.4f}))"
    d = rf"min({ang}\,2*PI-{ang})"
    return (rf"255*clip(({w:.4f}-{d})/{sf:.4f}\,0\,1)"
            rf"*clip((hypot(x-128\,y-128)-{chroma_floor:g})/{chroma_soft:g}\,0\,1)")


def _hold_hue(g: _Graph, hold: str, width_deg: float) -> None:
    """Black and white except ONE hue: a Cb/Cr hue-window mask (lut2 = a 256x256 table, cheap at 1080p) merges
    the colour frame over its own luma-grey copy."""
    src = g.flush()
    o, m, k, u, v, mo, mk = (g.label() for _ in range(7))
    g.parts.append(f"[{src}]split=3[{o}][{m}][{k}]")
    lum = (0.299, 0.587, 0.114)
    rows = [f"{ch}{c}={lum[j]:.4f}" for ch in "rgb" for j, c in enumerate("rgb")]
    g.parts.append(f"[{m}]colorchannelmixer={':'.join(rows)}[{mo}]")
    g.parts.append(f"[{k}]format=yuv444p,extractplanes=u+v[{u}][{v}]")
    g.parts.append(f"[{u}][{v}]lut2=c0='{hue_mask_expr(hold, width_deg)}',format=gbrp[{mk}]")
    out = g.label()
    g.parts.append(f"[{mo}][{o}][{mk}]maskedmerge[{out}]")
    g.cur = out


def levels_curve(levels: Any) -> str:
    """``[black, white, gamma]`` (0..1 input levels; gamma > 1 lifts the mids) -> a ``curves`` point list, '' when
    unset or a no-op. The Director's look guard measures the graded keyframes and sets these so a dark world (a
    dark-theme product in the noir room) still reads: whites reach white, lifted blacks go black, mids come up."""
    if not isinstance(levels, (list, tuple)) or len(levels) != 3:
        return ""
    try:
        b, w, gm = (float(x) for x in levels)
    except (TypeError, ValueError):
        return ""
    b = max(0.0, min(0.3, b))
    w = max(b + 0.3, min(1.0, w))
    gm = max(0.5, min(2.0, gm))
    if b < 0.004 and w > 0.996 and abs(gm - 1.0) < 0.02:
        return ""
    pts = [(0.0, 0.0)] if b > 0 else []
    for k in (0.0, 0.07, 0.25, 0.5, 0.75, 1.0):   # a linear toe below 7 %: the mids lift, black stays black
        x = b + (w - b) * k
        y = k if k < 0.1 else k ** (1.0 / gm)
        pts.append((x, y))
    if w < 1.0:
        pts.append((1.0, 1.0))
    return " ".join(f"{x:.3f}/{y:.3f}" for x, y in pts)


def _grade(g: _Graph, p: Mapping[str, Any], ow: int, oh: int) -> None:
    """The mood grade at output size, in planar RGB (every filter here supports gbrp)."""
    hold = p.get("hold")
    if hold and str(p.get("hold_mode") or "hue") == "hue":
        _hold_hue(g, str(hold), float(p.get("hold_width") or 12.0))
    elif hold:
        r, gg, b = _hex(str(hold))
        g.add(f"colorhold=color=0x{r:02x}{gg:02x}{b:02x}:similarity={float(p['hold_similarity']):g}"
              f":blend={float(p['hold_blend']):g}")
    mono = max(0.0, min(1.0, float(p.get("mono") or 0.0)))
    if mono > 0 and not hold:
        k = 1.0 - mono
        lum = (0.299, 0.587, 0.114)
        rows = []
        for i, ch in enumerate("rgb"):
            rows += [f"{ch}{c}={(k if i == j else 0.0) + mono * lum[j]:.4f}" for j, c in enumerate("rgb")]
        g.add("colorchannelmixer=" + ":".join(rows))
    sat = float(p.get("saturation") or 1.0)       # > 1 = punchier colour (anime), < 1 = muted
    if abs(sat - 1.0) > 1e-3:
        lum = (0.299, 0.587, 0.114)
        rows = [f"{ch}{c}={(sat if i == j else 0.0) + (1.0 - sat) * lum[j]:.4f}"
                for i, ch in enumerate("rgb") for j, c in enumerate("rgb")]
        g.add("colorchannelmixer=" + ":".join(rows))
    c = float(p.get("contrast") or 1.0)
    if abs(c - 1.0) > 1e-3:
        d = max(-0.2, min(0.2, 0.25 * (c - 1.0)))
        g.add(f"curves=all='0/0 0.25/{0.25 - d:.3f} 0.75/{0.75 + d:.3f} 1/1'")
    tint, amt = p.get("tint"), max(0.0, min(1.0, float(p.get("tint_amount") or 0.0)))
    if tint and amt > 0:
        r, gg, b = (v / 255.0 for v in _hex(str(tint)))
        g.add(f"colorchannelmixer=rr={1 - amt + amt * r:.4f}:gg={1 - amt + amt * gg:.4f}:bb={1 - amt + amt * b:.4f}")
    lv = levels_curve(p.get("levels"))
    if lv:
        g.add(f"curves=all='{lv}'")
    sm = float(p.get("smear") or 0.0)
    if sm > 0:
        g.add(f"gblur=sigma={sm:g}:sigmaV=0.01")
    sh = int(p.get("shift") or 0)
    if sh:
        g.add(f"rgbashift=rh={-sh}:bh={sh}:edge=smear")
    wob = int(p.get("wobble") or 0)
    if wob > 0:
        # horizontal tracking sway: crop a drifting window and scale it back (seeded by the frame number only)
        g.add(f"crop=w=iw-{2 * wob}:h=ih:x='{wob}+{wob}*sin(n*0.37)*sin(n*0.051)':y=0",
              f"scale={ow}:{oh}:flags=bilinear", "format=gbrp")
    band = max(0.0, min(1.0, float(p.get("band") or 0.0)))
    if band > 0:
        bh = max(2, oh // 36)
        g.add(f"drawbox=x=0:y={oh - bh}:w={ow}:h={bh}:color=white@{0.22 * band:.3f}:t=fill",
              f"drawbox=x=0:y={oh - bh - max(1, bh // 3)}:w={ow}:h={max(1, bh // 3)}:color=black@{0.35 * band:.3f}:t=fill",
              "format=gbrp")                      # drawbox may hand back YUV: the blends below need RGB again
