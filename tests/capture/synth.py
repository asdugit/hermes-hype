"""Synthetic product media for capture tests: a red car on a light-grey studio backdrop (Pillow only)."""
from __future__ import annotations

import random

from PIL import Image, ImageDraw, ImageFilter


def car_frame(w: int = 960, h: int = 540, *, x_shift: float = 0.0, seed: int = 1, gradient: bool = True,
              noise: int = 4, shadow: bool = True) -> tuple[Image.Image, Image.Image]:
    """(frame RGB, ground-truth mask L) - a red car with grey windows and black wheels on light grey."""
    rng = random.Random(seed)
    bg = Image.new("RGB", (w, h), (214, 216, 219))
    if gradient:   # soft studio falloff: lighter centre/top, darker floor
        d = ImageDraw.Draw(bg)
        for y in range(h):
            v = int(226 - 22 * (y / h) ** 1.5)
            d.line([(0, y), (w, y)], fill=(v, v + 1, v + 3))
    mask = Image.new("L", (w, h), 0)
    car = Image.new("RGB", (w, h), (0, 0, 0))
    cx = w * (0.5 + x_shift)
    by = h * 0.72
    body = [cx - w * 0.30, by - h * 0.20, cx + w * 0.30, by]
    cabin = [cx - w * 0.17, by - h * 0.36, cx + w * 0.13, by - h * 0.17]
    dc, dm = ImageDraw.Draw(car), ImageDraw.Draw(mask)
    if shadow:
        sh = Image.new("L", (w, h), 0)
        ImageDraw.Draw(sh).ellipse([cx - w * 0.33, by - h * 0.03, cx + w * 0.33, by + h * 0.05], fill=110)
        sh = sh.filter(ImageFilter.GaussianBlur(h * 0.02))
        bg = Image.composite(Image.new("RGB", (w, h), (120, 120, 124)), bg, sh)
    for dd, fill in ((dc, (200, 22, 30)), (dm, 255)):
        dd.rounded_rectangle(body, radius=int(h * 0.06), fill=fill)
        dd.rounded_rectangle(cabin, radius=int(h * 0.07), fill=fill)
    # windows: light grey-blue, very close to the backdrop colour (must stay opaque)
    win = [cabin[0] + w * 0.02, cabin[1] + h * 0.03, cabin[2] - w * 0.02, cabin[3] - h * 0.005]
    dc.rounded_rectangle(win, radius=int(h * 0.04), fill=(205, 210, 218))
    dc.line([(cx - w * 0.02, win[1]), (cx - w * 0.02, win[3])], fill=(200, 22, 30), width=max(2, w // 160))
    for wx in (cx - w * 0.19, cx + w * 0.19):
        r = h * 0.085
        for dd, fill in ((dc, (24, 24, 26)), (dm, 255)):
            dd.ellipse([wx - r, by - r, wx + r, by + r], fill=fill)
        dc.ellipse([wx - r * 0.45, by - r * 0.45, wx + r * 0.45, by + r * 0.45], fill=(170, 172, 176))
    frame = Image.composite(car, bg, mask.filter(ImageFilter.GaussianBlur(0.8)))
    if noise:
        px = frame.load()
        for _ in range(w * h // 6):
            x, y = rng.randrange(w), rng.randrange(h)
            r_, g_, b_ = px[x, y]
            n = rng.randint(-noise, noise)
            px[x, y] = (max(0, min(255, r_ + n)), max(0, min(255, g_ + n)), max(0, min(255, b_ + n)))
    return frame, mask


def busy_frame(w: int = 640, h: int = 360, seed: int = 3) -> Image.Image:
    """A textured, multi-coloured background (no cutout should be attempted)."""
    rng = random.Random(seed)
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for _ in range(400):
        x, y = rng.randrange(w), rng.randrange(h)
        s = rng.randint(10, 80)
        d.rectangle([x, y, x + s, y + s], fill=(rng.randrange(256), rng.randrange(256), rng.randrange(256)))
    return im


def iou(alpha, mask, thr: int = 128) -> float:
    """Intersection-over-union of alpha > thr and mask > thr."""
    a = alpha.tobytes()
    m = mask.tobytes()
    inter = sum(1 for x, y in zip(a, m, strict=False) if x > thr and y > thr)
    union = sum(1 for x, y in zip(a, m, strict=False) if x > thr or y > thr)
    return inter / union if union else 1.0
