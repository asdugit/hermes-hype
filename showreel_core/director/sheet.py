"""Keyframe planning and contact sheets for the vision critic (Pillow imported lazily)."""
from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# fractions of a shot sampled for k keyframes (k = 1/3/5 for quick/standard/max)
_FRACTIONS = {1: (0.6,), 2: (0.3, 0.8), 3: (0.2, 0.55, 0.9), 4: (0.12, 0.38, 0.64, 0.9),
              5: (0.1, 0.3, 0.5, 0.7, 0.9)}


@dataclass
class Frame:
    """One keyframe: which cell of the sheet, which shot, which time."""
    cell: int
    shot: str
    t: float
    local: float
    dur: float
    transition: str = ""
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def plan_keyframes(film: dict[str, Any], per_shot: int, *, max_frames: int = 30) -> list[Frame]:
    """Times to render for the critic: ``per_shot`` per shot, each transition's midpoint, and the 1 s hook."""
    shots = [s for s in film.get("shots") or [] if float(s["t1"]) > float(s["t0"])]
    trans = film.get("transitions") or []
    if not shots:
        return []
    k = max(1, min(5, per_shot))
    while k > 1 and k * len(shots) + len(trans) + 1 > max_frames:
        k -= 1
    raw: list[tuple[float, str, str]] = []
    for s in shots:
        t0, t1 = float(s["t0"]), float(s["t1"])
        for f in _FRACTIONS[k]:
            raw.append((round(t0 + f * (t1 - t0), 3), s["id"], ""))
    for tr in trans:   # 35 % into the window: mid-blend for wipes/fades, not the blank peak of a dip
        raw.append((round(float(tr["t"]) + 0.35 * float(tr["dur"]), 3), str(tr["to"]),
                    f"{tr['from']}->{tr['to']} {tr.get('type', '')}".strip()))
    if not any(abs(t - 1.0) < 0.35 for t, _, _ in raw):
        first = shots[0]
        raw.append((min(1.0, float(first["t1"]) - 0.05), first["id"], ""))
    raw.sort()
    by_id = {s["id"]: s for s in shots}
    frames: list[Frame] = []
    for t, sid, tr in raw[:max_frames]:
        s = next((x for x in shots if float(x["t0"]) <= t < float(x["t1"])), by_id.get(sid, shots[-1]))
        frames.append(Frame(len(frames) + 1, s["id"], t, round(t - float(s["t0"]), 3),
                            round(float(s["t1"]) - float(s["t0"]), 3), tr))
    return frames


# Sheets stay under the vision models' ~1568 px long edge, so nothing is downscaled again on the way in: each
# landscape keyframe reaches the critic at 768 px wide (40 % of 1080p). At the old 4-up layout (~386 px after the
# model's downscale) pixel art read as "static" and 1080p-legible type as "microscopic".
SHEET_LANDSCAPE = (768, 2, 6)       # cell width, columns, cells per sheet
SHEET_PORTRAIT = (360, 4, 8)


def contact_sheets(images: list[bytes], frames: list[Frame], out_dir: Path, *, prefix: str = "contact",
                   cell_w: int | None = None, cols: int | None = None, max_cells: int | None = None) -> list[Path]:
    """Lay keyframes out on numbered sheets (JPEG); returns the sheet paths."""
    from PIL import Image, ImageDraw

    out_dir.mkdir(parents=True, exist_ok=True)
    pics = []
    for data in images:
        try:
            pics.append(Image.open(io.BytesIO(data)).convert("RGB"))
        except Exception:  # noqa: BLE001 - a broken capture becomes a grey cell
            pics.append(None)
    sample = next((p for p in pics if p is not None), None)
    aspect = (sample.height / sample.width) if sample else 9 / 16
    portrait = aspect > 1.0
    dcw, dcols, dmax = SHEET_PORTRAIT if portrait else SHEET_LANDSCAPE
    cell_w = cell_w or dcw
    cols = cols or dcols
    max_cells = max_cells or dmax
    cell_h = round(cell_w * aspect)
    label_h = 30
    font = _font(20)
    paths: list[Path] = []
    for start in range(0, len(frames), max_cells):
        chunk = list(zip(frames[start:start + max_cells], pics[start:start + max_cells], strict=False))
        rows = (len(chunk) + cols - 1) // cols
        gap = 6
        sheet = Image.new("RGB", (cols * cell_w + (cols + 1) * gap, rows * (cell_h + label_h) + (rows + 1) * gap),
                          (24, 24, 28))
        draw = ImageDraw.Draw(sheet)
        for i, (fr, pic) in enumerate(chunk):
            x = gap + (i % cols) * (cell_w + gap)
            y = gap + (i // cols) * (cell_h + label_h + gap)
            label = f"{fr.cell}  {fr.shot}  {fr.t:.1f}s" + (f"  [{fr.transition}]" if fr.transition else "")
            draw.rectangle((x, y, x + cell_w, y + label_h), fill=(0, 0, 0))
            draw.text((x + 8, y + 4), label, fill=(255, 230, 120), font=font)
            if pic is None:
                draw.rectangle((x, y + label_h, x + cell_w, y + label_h + cell_h), fill=(90, 90, 90))
                draw.text((x + 8, y + label_h + 8), "capture failed", fill=(255, 255, 255), font=font)
            else:
                sheet.paste(pic.resize((cell_w, cell_h), Image.Resampling.LANCZOS), (x, y + label_h))
        p = out_dir / f"{prefix}-{start // max_cells + 1}.jpg"
        sheet.save(p, "JPEG", quality=88)
        paths.append(p)
    return paths


def thumbnail(data: bytes, out_path: Path, width: int = 480) -> Path | None:
    """Save a JPEG thumbnail of a captured frame (library entries). Returns None on failure."""
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data)).convert("RGB")
        h = round(width * im.height / im.width)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        im.resize((width, h), Image.Resampling.LANCZOS).save(out_path, "JPEG", quality=86)
        return out_path
    except Exception:  # noqa: BLE001 - a thumbnail is nice to have
        return None


def _font(size: int) -> Any:
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()
