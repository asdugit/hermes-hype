"""Background removal for product media on a uniform or near-uniform backdrop (Pillow only, no numpy).

Method (fast enough for short clips: tens of ms per 720p frame):

1. **Backdrop model** from the outer border band of a ~192 px thumbnail: a flat colour (median) or,
   if that explains the border poorly, a smooth quadratic gradient per channel
   (``c = a + b x + c y + d x^2 + e y^2``, fitted by trimmed least squares). If the model explains
   < 70 % of the border, or the backdrop is textured, there is NO cutout (``grade="none"``).
2. **Soft key**: per-pixel L1 distance to the backdrop -> alpha ramp between a noise-derived low
   threshold and a high threshold (anti-aliased edges, soft shadows stay semi-transparent).
3. **Hole protection**: backdrop-coloured regions not connected to the frame border (car windows,
   grey trim inside the body) stay opaque; computed by flood fill on a low-res mask.
4. Light feather + choke to remove the grey fringe.

Quality is measured, not assumed (``grade`` good | fair | poor | none, ``score`` 0..1), so kits can
decide whether to use the cutout.
"""
from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any

from PIL import Image, ImageChops, ImageFilter

WORK_SIDE = 192          # thumbnail used for the backdrop fit and the topology passes
FLAT_TOL = 30            # L1 distance (sum of 3 channels) for a border sample to count as backdrop
MIN_INLIERS = 0.70
MAX_NOISE = 26.0


@dataclass
class BackgroundModel:
    """Backdrop colour model in normalised coordinates (x, y in [-1, 1])."""
    kind: str                                   # flat | gradient
    coef: list[list[float]]                     # per channel: [a, b, c, d, e]
    mean: tuple[int, int, int]
    inliers: float                              # share of border samples explained (<= FLAT_TOL)
    noise: float                                # p90 L1 residual of the inliers

    def color(self, x: float, y: float) -> tuple[int, int, int]:
        out = []
        for a, b, c, d, e in self.coef:
            v = a + b * x + c * y + d * x * x + e * y * y
            out.append(max(0, min(255, round(v))))
        return out[0], out[1], out[2]

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "bg": "#{:02x}{:02x}{:02x}".format(*self.mean), "inliers": round(self.inliers, 3),
                "noise": round(self.noise, 1)}


@dataclass
class CutoutQuality:
    """Measured quality of one cutout."""
    ok: bool = False
    grade: str = "none"          # good | fair | poor | none
    score: float = 0.0
    reason: str = ""
    model: dict[str, Any] = field(default_factory=dict)
    fg_fraction: float = 0.0     # opaque share of the frame
    edge_touch: float = 0.0      # share of the frame border covered by the subject
    fragments: int = 0           # opaque components >= 0.2 % of the frame
    largest_share: float = 0.0   # largest component / all opaque area
    holes_kept: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _thumb(img: Image.Image, side: int = WORK_SIDE) -> Image.Image:
    im = img.convert("RGB")
    w, h = im.size
    s = side / max(w, h)
    return im.resize((max(8, round(w * s)), max(8, round(h * s))), Image.Resampling.BOX) if s < 1 else im


def _border_samples(im: Image.Image) -> list[tuple[float, float, tuple[int, int, int]]]:
    w, h = im.size
    band = max(2, round(0.04 * min(w, h)))
    px = im.load()
    assert px is not None
    out = []
    for y in range(h):
        edge_row = y < band or y >= h - band
        for x in (range(w) if edge_row else (*range(band), *range(w - band, w))):
            out.append((2 * x / (w - 1) - 1, 2 * y / (h - 1) - 1, px[x, y]))
    return out


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting (tiny dense systems)."""
    n = len(b)
    m = [[*row[:], b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-9:
            return None
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def _fit_quadratic(samples: list[tuple[float, float, tuple[int, int, int]]]) -> list[list[float]] | None:
    coefs = []
    for ch in range(3):
        ata = [[0.0] * 5 for _ in range(5)]
        atb = [0.0] * 5
        for x, y, c in samples:
            f = (1.0, x, y, x * x, y * y)
            v = c[ch]
            for i in range(5):
                fi = f[i]
                atb[i] += fi * v
                row = ata[i]
                for j in range(5):
                    row[j] += fi * f[j]
        sol = _solve(ata, atb)
        if sol is None:
            return None
        coefs.append(sol)
    return coefs


def _residuals(samples, model_color) -> list[float]:
    return [abs(c[0] - m[0]) + abs(c[1] - m[1]) + abs(c[2] - m[2])
            for (x, y, c), m in zip(samples, (model_color(x, y) for x, y, _ in samples), strict=True)]


def _p(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return s[min(len(s) - 1, int(q * (len(s) - 1)))]


def _samples(img: Image.Image) -> list[tuple[float, float, tuple[int, int, int]]]:
    samples = _border_samples(_thumb(img))
    if len(samples) > 1500:
        samples = samples[:: len(samples) // 1500 + 1]
    return samples


def model_fit(model: BackgroundModel, img: Image.Image) -> float:
    """Share of ``img``'s border explained by ``model`` (reuse a model across video frames)."""
    samples = _samples(img)
    if not samples:
        return 0.0
    return sum(r <= FLAT_TOL for r in _residuals(samples, model.color)) / len(samples)


def fit_background(img: Image.Image) -> BackgroundModel | None:
    """Fit a flat or gradient backdrop to the frame border; None if the background is busy."""
    samples = _samples(img)
    if len(samples) < 50:
        return None
    med = tuple(int(statistics.median(c[ch] for _, _, c in samples)) for ch in range(3))
    flat = BackgroundModel("flat", [[float(med[ch]), 0, 0, 0, 0] for ch in range(3)], med, 0.0, 0.0)  # type: ignore[arg-type]
    res = _residuals(samples, flat.color)
    flat.inliers = sum(r <= FLAT_TOL for r in res) / len(res)
    flat.noise = _p([r for r in res if r <= FLAT_TOL], 0.9)
    best = flat
    if flat.inliers < 0.97:
        keep = samples
        coef = None
        for _ in range(3):                       # trimmed least squares: drop the worst 20 % each round
            coef = _fit_quadratic(keep)
            if coef is None:
                break
            g = BackgroundModel("gradient", coef, med, 0.0, 0.0)   # type: ignore[arg-type]
            r = _residuals(keep, g.color)
            cut = _p(r, 0.8)
            keep = [s for s, rr in zip(keep, r, strict=True) if rr <= max(cut, 6)]
            if len(keep) < 40:
                break
        if coef is not None:
            g = BackgroundModel("gradient", coef, med, 0.0, 0.0)   # type: ignore[arg-type]
            res_g = _residuals(samples, g.color)
            g.inliers = sum(r <= FLAT_TOL for r in res_g) / len(res_g)
            g.noise = _p([r for r in res_g if r <= FLAT_TOL], 0.9)
            g.mean = g.color(0.0, 0.0)
            if g.inliers >= flat.inliers + 0.03:
                best = g
    if best.inliers < MIN_INLIERS or best.noise > MAX_NOISE:
        return None
    return best


def render_background(model: BackgroundModel, size: tuple[int, int]) -> Image.Image:
    """The backdrop model as an RGB image of ``size``."""
    if model.kind == "flat":
        return Image.new("RGB", size, model.mean)
    w, h = size
    gw = 64
    gh = max(2, round(gw * h / max(1, w)))
    grid = Image.new("RGB", (gw, gh))
    px = grid.load()
    assert px is not None
    for y in range(gh):
        for x in range(gw):
            px[x, y] = model.color(2 * x / (gw - 1) - 1, 2 * y / (gh - 1) - 1)
    return grid.resize(size, Image.Resampling.BILINEAR)


def _flood_border(mask: bytearray, w: int, h: int) -> bytearray:
    """Cells of ``mask`` (nonzero) connected to the image border (4-connectivity)."""
    seen = bytearray(w * h)
    q: deque[int] = deque()
    for x in range(w):
        for i in (x, (h - 1) * w + x):
            if mask[i] and not seen[i]:
                seen[i] = 1
                q.append(i)
    for y in range(h):
        for i in (y * w, y * w + w - 1):
            if mask[i] and not seen[i]:
                seen[i] = 1
                q.append(i)
    while q:
        i = q.popleft()
        x, y = i % w, i // w
        for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1, (i - w) if y else -1,
                  (i + w) if y < h - 1 else -1):
            if j >= 0 and mask[j] and not seen[j]:
                seen[j] = 1
                q.append(j)
    return seen


def _components(mask: bytearray, w: int, h: int) -> list[list[int]]:
    """4-connected components of nonzero cells (lists of indices)."""
    seen = bytearray(w * h)
    comps = []
    for start in range(w * h):
        if not mask[start] or seen[start]:
            continue
        seen[start] = 1
        comp, q = [], deque([start])
        while q:
            i = q.popleft()
            comp.append(i)
            x, y = i % w, i // w
            for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1, (i - w) if y else -1,
                      (i + w) if y < h - 1 else -1):
                if j >= 0 and mask[j] and not seen[j]:
                    seen[j] = 1
                    q.append(j)
        comps.append(comp)
    return comps


def _lut(fn) -> list[int]:
    return [max(0, min(255, int(fn(v)))) for v in range(256)]


def shadow_mask(rgb: Image.Image, bgimg: Image.Image, *, darkest: float = 0.22) -> Image.Image:
    """255 where a pixel looks like a cast shadow on the backdrop: no more saturated than the backdrop
    (+25), darker than it (< 97 % value) but not near-black (>= ``darkest`` of its value). Black tyres
    and coloured paint fail the test; windows are handled by hole protection."""
    _, si, vi = rgb.convert("HSV").split()
    _, sb, vb = bgimg.convert("HSV").split()
    not_sat = ImageChops.subtract(si, sb).point(_lut(lambda v: 255 if v <= 25 else 0))
    darker = ImageChops.subtract(vb.point(_lut(lambda v: v * 0.97)), vi).point(_lut(lambda v: 255 if v > 0 else 0))
    not_black = ImageChops.subtract(vi, vb.point(_lut(lambda v: v * darkest))).point(
        _lut(lambda v: 255 if v > 0 else 0))
    return ImageChops.multiply(ImageChops.multiply(not_sat, darker), not_black)


def cutout(img: Image.Image, *, model: BackgroundModel | None = None, feather: float | None = None,
           keep_shadow: bool = False) -> tuple[Image.Image | None, CutoutQuality]:
    """RGBA cutout of the subject + its measured quality (image None when there is no usable backdrop).

    Cast shadows connected to the backdrop are removed unless ``keep_shadow`` (then they stay as
    semi-opaque grey, which only looks right on a similar backdrop).
    """
    rgb = img.convert("RGB")
    model = model or fit_background(rgb)
    if model is None:
        return None, CutoutQuality(reason="background is not uniform")
    w, h = rgb.size
    bgimg = render_background(model, (w, h))
    r, g, b = ImageChops.difference(rgb, bgimg).split()
    dist = ImageChops.add(ImageChops.add(r, g), b)            # L1 distance, saturating at 255
    t_lo = max(18.0, min(70.0, model.noise * 1.5 + 8))
    t_hi = t_lo + max(24.0, t_lo * 0.8)
    lut = [0 if v <= t_lo else 255 if v >= t_hi else round((v - t_lo) * 255 / (t_hi - t_lo)) for v in range(256)]
    alpha = dist.point(lut)
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))   # opening: drop noise specks
    shadow = None if keep_shadow else shadow_mask(rgb, bgimg)

    # topology on a thumbnail: what is connected to the frame border through backdrop-like (or shadow) cells.
    # A cell is backdrop-like/passable only if ALL its pixels are (BOX average of a binary mask == pooling),
    # so thin opaque lines such as window pillars or tyre walls still close a region at thumbnail size.
    sw, sh = _thumb(rgb).size
    scale = w / sw
    hard = alpha.point([0] * 250 + [255] * 6)              # 255 = clearly not backdrop
    bglike = bytearray(1 if v <= 2 else 0 for v in hard.resize((sw, sh), Image.Resampling.BOX).tobytes())
    dbytes = dist.resize((sw, sh), Image.Resampling.BOX).tobytes()
    open_px = alpha.point([255] * 250 + [0] * 6)          # full-res backdrop-like pixels (255)
    if shadow is not None:   # passable = backdrop-like or shadow-like
        open_px = ImageChops.lighter(open_px, shadow)
        passable = bytearray(1 if v >= 253 else 0
                             for v in open_px.resize((sw, sh), Image.Resampling.BOX).tobytes())
    else:
        passable = bglike
    outside = _flood_border(passable, sw, sh)
    if shadow is not None:
        # remove shadow pixels connected to the backdrop: seed = the fully passable thumbnail cells, then
        # geodesic growth at full resolution through passable pixels only (exact edges, walls are never
        # crossed). Only the box around non-backdrop pixels needs the (rank-filter) growth.
        seed = Image.frombytes("L", (sw, sh), bytes(255 if v else 0 for v in outside))
        region = ImageChops.darker(seed.resize((w, h), Image.Resampling.NEAREST), open_px)
        box = ImageChops.lighter(hard, shadow).getbbox()
        if box:
            m = math.ceil(2 * scale) + 2
            box = (max(0, box[0] - m), max(0, box[1] - m), min(w, box[2] + m), min(h, box[3] + m))
            sub, gate = region.crop(box), open_px.crop(box)
            for _ in range(math.ceil(scale / 2) + 1):
                sub = ImageChops.darker(sub.filter(ImageFilter.MaxFilter(5)), gate)
            region.paste(sub, box[:2])
        cast = ImageChops.multiply(shadow, region).filter(ImageFilter.GaussianBlur(0.8))
        alpha = ImageChops.subtract(alpha, cast)
    # holes: backdrop-like regions (below the HIGH threshold) not connected to the border stay opaque
    holes = bytearray(1 if bglike[i] and not outside[i] else 0 for i in range(sw * sh))
    kept = 0
    n = sw * sh
    for comp in _components(holes, sw, sh):
        mean_d = sum(dbytes[i] for i in comp) / len(comp)
        if len(comp) > 0.04 * n and mean_d < t_lo * 0.35:   # a big clean gap shows the backdrop itself
            for i in comp:
                holes[i] = 0
        else:
            kept += 1
    if kept:
        protect = Image.frombytes("L", (sw, sh), bytes(255 if v else 0 for v in holes))
        protect = protect.filter(ImageFilter.MaxFilter(3)).resize((w, h), Image.Resampling.BILINEAR)
        alpha = ImageChops.lighter(alpha, protect)

    radius = feather if feather is not None else max(0.6, min(w, h) / 900)
    alpha = alpha.filter(ImageFilter.GaussianBlur(radius))
    alpha = alpha.point([0 if v <= 24 else 255 if v >= 231 else round((v - 24) * 255 / 207) for v in range(256)])
    out = Image.composite(rgb, Image.new("RGB", (w, h), (0, 0, 0)), alpha.point([0] + [255] * 255))
    out.putalpha(alpha)
    q = measure(alpha, model)
    q.holes_kept = kept
    return out, q


def measure(alpha: Image.Image, model: BackgroundModel) -> CutoutQuality:
    """Score a cutout alpha matte (coverage, border contact, fragmentation, backdrop fit)."""
    sw, sh = _thumb(alpha.convert("RGB")).size
    a = alpha.resize((sw, sh), Image.Resampling.BOX).tobytes()
    n = sw * sh
    fg = bytearray(1 if v > 128 else 0 for v in a)
    fg_n = sum(fg)
    ring = [x for x in range(sw)] + [(sh - 1) * sw + x for x in range(sw)] + \
           [y * sw for y in range(1, sh - 1)] + [y * sw + sw - 1 for y in range(1, sh - 1)]
    edge = sum(fg[i] for i in ring) / len(ring)
    comps = [c for c in _components(fg, sw, sh) if len(c) >= 0.002 * n]
    largest = max((len(c) for c in comps), default=0)
    q = CutoutQuality(model=model.to_dict(), fg_fraction=round(fg_n / n, 4), edge_touch=round(edge, 4),
                      fragments=len(comps), largest_share=round(largest / fg_n, 3) if fg_n else 0.0)
    score = 1.0
    score -= max(0.0, 0.92 - model.inliers) * 2.0
    score -= max(0.0, model.noise - 16) / 40
    if not 0.02 <= q.fg_fraction <= 0.8:
        score -= 0.5
        q.reason = "subject too small" if q.fg_fraction < 0.02 else "subject fills the frame"
    score -= q.edge_touch * 1.2
    score -= max(0.0, 0.85 - q.largest_share)
    score -= min(0.3, 0.05 * max(0, q.fragments - 3))
    q.score = round(max(0.0, min(1.0, score)), 3)
    q.grade = "good" if q.score >= 0.75 else "fair" if q.score >= 0.5 else "poor"
    q.ok = q.grade in ("good", "fair")
    if not q.reason:
        q.reason = {"good": "clean backdrop", "fair": "usable with care", "poor": "unreliable matte"}[q.grade]
    return q
