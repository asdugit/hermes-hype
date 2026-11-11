"""Media artifacts -> assets: image copies, video posters + cutout frames (ffmpeg), PDF facts."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image
from synth import busy_frame, car_frame

from showreel_core.capture.media import fit_size, frame_interest, image_asset, pdf_info, video_asset


def make_video(ffmpeg: str, out: Path, frames: list[Image.Image], fps: int = 10) -> Path:
    d = out.parent / (out.stem + "_frames")
    d.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(frames):
        f.save(d / f"{i:03d}.png")
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(fps), "-i",
                    str(d / "%03d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(out)],
                   check=True, capture_output=True, timeout=120)
    return out


def test_fit_size_even_and_bounded():
    assert fit_size(1920, 1080, 720) == (720, 404)
    assert fit_size(100, 50, 720) == (100, 50)
    assert fit_size(1080, 1920, 720)[1] == 720


def test_image_asset_copy_and_cutout(tmp_path):
    src = tmp_path / "car.png"
    car_frame()[0].save(src)
    a = image_asset(src, tmp_path / "out")
    assert a.error is None and (a.w, a.h) == (960, 540) and a.format == "PNG"
    assert Path(a.path).read_bytes() == src.read_bytes()
    assert a.cutout and a.cutout["grade"] == "good" and Path(a.cutout["path"]).is_file()
    assert a.accent.startswith("#") and a.palette


def test_image_asset_exif_rotation_and_no_cutout_on_busy(tmp_path):
    src = tmp_path / "busy.jpg"
    im = busy_frame(320, 180)
    exif = Image.Exif()
    exif[0x0112] = 6                       # rotate 90 CW on display
    im.save(src, exif=exif)
    a = image_asset(src, tmp_path / "out")
    assert (a.w, a.h) == (180, 320) and a.path.endswith(".png")
    assert a.cutout and a.cutout["grade"] == "none" and "path" not in a.cutout


def test_svg_and_unreadable_images(tmp_path):
    svg = tmp_path / "logo.svg"
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40"></svg>', encoding="utf-8")
    a = image_asset(svg, tmp_path / "o1")
    assert (a.w, a.h) == (120, 40) and a.format == "SVG" and a.cutout is None
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    b = image_asset(bad, tmp_path / "o2")
    assert b.error and b.error["code"] == "image"


def test_frame_interest_prefers_content_over_black():
    black = Image.new("RGB", (64, 36))
    assert frame_interest(car_frame(160, 90)[0]) > frame_interest(black)


def test_video_poster_and_cutout_frames(tmp_path, ffmpeg_bin):
    frames = [Image.new("RGB", (480, 270))] + [car_frame(480, 270, x_shift=-0.15 + 0.3 * i / 19, seed=i)[0]
                                               for i in range(20)]
    src = make_video(ffmpeg_bin, tmp_path / "car.mp4", frames)
    a = video_asset(src, tmp_path / "out", ffmpeg=ffmpeg_bin, cutout_fps=10, cutout_max_side=320)
    assert a.error is None, a.error
    assert (a.w, a.h) == (480, 270) and abs((a.duration_s or 0) - 2.1) < 0.15 and a.fps == 10
    assert a.poster_t and a.poster_t > 0.1           # the black first frame is not the poster
    assert Path(a.path).is_file()
    c = a.cutout
    assert c and c["grade"] in ("good", "fair") and c["ok"] and c["count"] == 21 and (c["w"], c["h"]) == (320, 180)
    files = sorted(Path(c["frames_dir"]).glob("*.png"))
    assert len(files) == 21 and files[0].name == "000001.png"
    with Image.open(files[10]) as f:
        assert f.mode == "RGBA" and f.getchannel("A").getextrema() == (0, 255)
    assert Path(c["still"]["path"]).is_file() and c["still"]["grade"] == "good"
    assert c["frame_grades"].get("good", 0) >= 15


def test_video_cutout_respects_deadline(tmp_path, ffmpeg_bin):
    frames = [car_frame(320, 180, x_shift=0.01 * i, seed=i)[0] for i in range(30)]
    src = make_video(ffmpeg_bin, tmp_path / "car.mp4", frames)
    import time
    a = video_asset(src, tmp_path / "out", ffmpeg=ffmpeg_bin, cutout_fps=10, deadline=time.monotonic() + 0.01)
    assert a.error is None and a.cutout and a.cutout["partial"] and a.cutout["count"] < 30


def test_video_on_busy_background_has_no_cutout(tmp_path, ffmpeg_bin):
    src = make_video(ffmpeg_bin, tmp_path / "busy.mp4", [busy_frame(320, 180, seed=i) for i in range(10)])
    a = video_asset(src, tmp_path / "out", ffmpeg=ffmpeg_bin)
    assert a.error is None and a.cutout and a.cutout["grade"] == "none" and a.cutout["frames"] == 0
    assert not (tmp_path / "out" / "cutout").exists()


def test_not_a_video(tmp_path, ffmpeg_bin):
    bad = tmp_path / "x.mp4"
    bad.write_bytes(b"\0" * 100)
    a = video_asset(bad, tmp_path / "out", ffmpeg=ffmpeg_bin)
    assert a.error and a.error["code"] == "ffmpeg"


def test_pdf_info(tmp_path):
    p = tmp_path / "doc.pdf"
    Image.new("RGB", (200, 260), "white").save(p, save_all=True, append_images=[Image.new("RGB", (200, 260))],
                                                title="Quarterly Plan")
    a = pdf_info(p)
    assert a.pages == 2 and a.title == "Quarterly Plan" and a.error is None


def test_real_car_clip_if_present(tmp_path, ffmpeg_bin):
    """WP-K2's procedural car clip (dev machines only: set HYPE_TESTMEDIA to its folder).

    ``car_alpha/`` holds the ground-truth matte; glass that mirrors the backdrop at the silhouette
    edge is a known miss, so the bar is a mean IoU of 0.85, not 0.95.
    """
    import os

    root = Path(os.environ.get("HYPE_TESTMEDIA", "")) if os.environ.get("HYPE_TESTMEDIA") else None
    if root is None or not (root / "car.mp4").is_file():
        pytest.skip("set HYPE_TESTMEDIA to the folder holding car.mp4 (+ car_alpha/)")
    a = video_asset(root / "car.mp4", tmp_path / "out", ffmpeg=ffmpeg_bin)
    assert a.error is None and a.cutout and a.cutout["ok"] and a.cutout["count"] > 0
    gt_dir = root / "car_alpha"
    if gt_dir.is_dir():
        from synth import iou
        scores = []
        for k in range(1, a.cutout["count"] + 1, 10):
            mine = Image.open(Path(a.cutout["frames_dir"]) / f"{k:06d}.png").getchannel("A")
            src_i = round((k - 1) / a.cutout["fps"] * (a.fps or 30)) + 1
            gt = Image.open(gt_dir / f"{src_i:06d}.png").getchannel("A").resize(mine.size, Image.Resampling.BOX)
            scores.append(iou(mine, gt))
        assert sum(scores) / len(scores) > 0.85, scores
