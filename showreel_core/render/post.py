"""Named ffmpeg post-processing chains applied inside the per-chunk encode (no extra pass).

A chain spec is one name or several joined with ``+`` (e.g. ``"bloom+grain_vignette"``).
Stage order is fixed regardless of the spec order:

1. decode JPEG (full-range BT.601) -> planar RGB
2. ``pixel``: fixed palette (``paletteuse dither=none``) at the internal size
3. resize to the output size (nearest-neighbour for ``pixel``, lanczos otherwise)
4. RGB effects at output size: ``bloom``; ``crt`` glow
5. one static multiply mask (vignette and/or CRT scanlines), then CRT curvature
6. -> yuv420p BT.709 limited range, then seeded luma grain (``grain_vignette``)

The mask is a Pillow-generated greyscale PNG decoded once and repeated with the ``loop`` filter:
~1.3 ms/frame at 1080p versus ~10.5 ms for ``drawgrid`` + ``vignette`` (both single-threaded).
Every random source is seeded (``noise`` gets an explicit seed; its default -1 is random).
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .errors import RenderError

POST_CHAINS = ("none", "grain_vignette", "pixel", "crt", "bloom")

DEFAULTS: dict[str, dict[str, Any]] = {
    # vignette = darkening at the frame corners (0..1); grain = ffmpeg noise strength on luma
    "grain_vignette": {"grain": 7, "vignette": 0.35},
    "pixel": {"palette": None},
    # scanline = darkening of every period-th row; period None -> round(out_h / 360) (3 px at 1080p)
    "crt": {"glow": 0.35, "scanline": 0.30, "period": None, "curvature": 0.05, "vignette": 0.45},
    "bloom": {"threshold": 222, "amount": 0.55, "sigma": 6.0},
}

# Filters each chain needs (checked against the ffmpeg capability probe).
REQUIRED_FILTERS: dict[str, tuple[str, ...]] = {
    "none": ("scale", "format"),
    "grain_vignette": ("blend", "loop", "noise"),
    "pixel": ("paletteuse",),
    "crt": ("split", "gblur", "blend", "loop", "lenscorrection"),
    "bloom": ("split", "lutrgb", "gblur", "blend"),
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
