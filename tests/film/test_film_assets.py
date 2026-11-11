"""Product media prep: images resized/re-encoded, videos and image folders -> frame sequences + manifest entries."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from showreel_core.film.assets import AssetError, frame_count_ok, prepare_asset


def _img(path: Path, size=(3000, 1500), mode="RGB") -> Path:
    Image.new(mode, size, (200, 30, 40, 128) if mode == "RGBA" else (200, 30, 40)).save(path)
    return path


def test_image_is_downscaled_to_jpeg(tmp_path: Path):
    e = prepare_asset("shot", {"src": str(_img(tmp_path / "a.png"))}, tmp_path / "job")
    assert e == {"type": "image", "w": 1920, "h": 960, "path": "assets/shot/image.jpg"}
    with Image.open(tmp_path / "job" / e["path"]) as im:
        assert im.size == (1920, 960)


def test_alpha_image_stays_png_and_small_images_are_not_upscaled(tmp_path: Path):
    e = prepare_asset("logo", {"src": str(_img(tmp_path / "l.png", (400, 300), "RGBA"))}, tmp_path / "job")
    assert e["path"].endswith(".png") and (e["w"], e["h"]) == (400, 300)


def test_image_with_cutout(tmp_path: Path):
    e = prepare_asset("car", {"src": str(_img(tmp_path / "c.jpg")), "cutout": str(_img(tmp_path / "cut.png", mode="RGBA"))},
                      tmp_path / "job")
    assert e["cutout"]["path"] == "assets/car/cutout/image.png"


def test_image_folder_becomes_frames(tmp_path: Path):
    d = tmp_path / "seq"
    d.mkdir()
    for i in range(5):
        _img(d / f"x{i:02d}.png", (1280, 720))
    e = prepare_asset("seq", {"src": str(d), "fps": 60, "poster": True}, tmp_path / "job", fps=24)
    assert e["type"] == "frames" and e["count"] == 5 and e["fps"] == 24 and (e["w"], e["h"]) == (960, 540)
    assert e["pattern"] == "assets/seq/%06d.jpg" and e["poster"] == "assets/seq/poster.jpg"
    assert abs(e["dur"] - 5 / 24) < 1e-3


def test_missing_source(tmp_path: Path):
    with pytest.raises(AssetError, match="does not exist"):
        prepare_asset("x", {"src": str(tmp_path / "nope.mp4")}, tmp_path / "job")


def test_unknown_type(tmp_path: Path):
    p = tmp_path / "a.xyz"
    p.write_text("?", encoding="utf-8")
    with pytest.raises(AssetError, match="media type"):
        prepare_asset("x", {"src": str(p)}, tmp_path / "job")


def test_video_to_frames(tmp_path: Path, ffmpeg_path: str):
    src = tmp_path / "clip.mp4"
    subprocess.run([ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=1280x720:rate=50:duration=2", "-pix_fmt", "yuv420p", str(src)], check=True)
    e = prepare_asset("car", {"src": str(src), "poster": 1.0, "t0": 0.5}, tmp_path / "job", fps=30, ffmpeg=ffmpeg_path)
    assert e["type"] == "frames" and e["fps"] == 30 and (e["w"], e["h"]) == (960, 540)
    assert 44 <= e["count"] <= 46 and frame_count_ok(tmp_path / "job", e)
    assert e["poster"] == "assets/car/poster.jpg"


def test_video_to_frames_in_a_folder_with_percent_and_quotes(tmp_path: Path, ffmpeg_path: str):
    """ffmpeg's image2 output pattern read a literal '%' in the job folder as a placeholder (exit -22)."""
    root = tmp_path / "100% it's ünï"
    root.mkdir()
    src = root / "clip.mp4"
    subprocess.run([ffmpeg_path, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=320x180:rate=10:duration=1", "-pix_fmt", "yuv420p", str(src)], check=True)
    e = prepare_asset("clip", {"src": str(src)}, root / "job", fps=10, ffmpeg=ffmpeg_path)
    assert e["type"] == "frames" and 9 <= e["count"] <= 11 and frame_count_ok(root / "job", e)
