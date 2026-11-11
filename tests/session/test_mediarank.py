"""Session picture ranking (session.mediarank): debug artefacts are set aside, real shots are kept.

All pictures are synthetic and generated here (never a user's real images)."""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from showreel_core.contracts import Event
from showreel_core.session.mediarank import (analyze_pixels, is_junk, name_signals, propagate, rank_media,
                                             retry_base, tokens)

PIL = pytest.importorskip("PIL")
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402


def scene(w: int, h: int, seed: int) -> Image.Image:
    """A colourful, detailed 'gameplay' picture: sky gradient, ground, many coloured shapes."""
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    top = (rnd.randint(20, 90), rnd.randint(60, 140), rnd.randint(150, 240))
    for y in range(h):
        u = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(c * (1 - 0.6 * u) + 40 * u) for c in top))
    d.rectangle([0, int(h * 0.62), w, h], fill=(rnd.randint(60, 120), rnd.randint(90, 160), rnd.randint(30, 70)))
    for _ in range(70):
        x, y = rnd.randint(-20, w), rnd.randint(int(h * 0.2), h)
        s = rnd.randint(6, max(8, w // 9))
        col = (rnd.randint(30, 255), rnd.randint(30, 255), rnd.randint(30, 255))
        if rnd.random() < 0.5:
            d.rectangle([x, y - s, x + s, y], fill=col, outline=(20, 20, 20))
        else:
            d.ellipse([x, y - s, x + s, y], fill=col, outline=(240, 240, 240))
    return im.filter(ImageFilter.SMOOTH)


def sheet(cols: int, rows: int, tw: int, th: int, gutter: int = 0, seed: int = 100) -> Image.Image:
    """A contact sheet: cols x rows different scenes, butted together or with gutters."""
    W, H = cols * tw + (cols - 1) * gutter, rows * th + (rows - 1) * gutter
    out = Image.new("RGB", (W, H), (12, 12, 12))
    for r in range(rows):
        for c in range(cols):
            out.paste(scene(tw, th, seed + r * cols + c), (c * (tw + gutter), r * (th + gutter)))
    return out


def ev(eid: str, path: Path, t: float = 0.0, kind: str = "screenshot", **data) -> Event:
    return Event(id=eid, t=t, kind=kind, tool="x", title=path.name, summary="", data={"path": str(path), **data},
                 ok=True, weight=0.8)


@pytest.fixture()
def pics(tmp_path: Path) -> dict[str, Path]:
    p = {}
    for name, im in {
        "gameplay_lobby.png": scene(960, 540, 1),
        "street_night.png": scene(960, 540, 2),
        "bank_interior.png": scene(960, 540, 3),
        "suspects_overview.png": sheet(2, 2, 480, 270, seed=10),          # a 2x2 sheet with an innocent name
        "lineup.png": sheet(3, 1, 400, 400, gutter=12, seed=20),          # 3 tiles with gutters
        "street_render.png": scene(960, 540, 4).convert("L").convert("RGB"),   # a B&W lighting test
        "g_heads_owen2.png": scene(900, 540, 5),                          # debug token in the name
        "heads_strip.png": sheet(5, 1, 360, 360, seed=30),                # 1800x360 strip
        "tiny.png": scene(120, 90, 6),
    }.items():
        im.save(tmp_path / name)
        p[name] = tmp_path / name
    return p


def test_tokens_and_retry_base() -> None:
    assert tokens("e1401_g_heads_owen2.jpg") == ["g", "heads", "owen", "2"]
    assert tokens("zf_40_0_1.jpg")[0] == "zf"
    assert retry_base("e1403_g_heads_owen3.jpg") == "g_heads_owen"
    assert retry_base("hd_owen4_55.png") == "hd_owen"
    assert retry_base("lobby.png") == ""
    why, bonus = name_signals("g_flicker_bw_a.jpg")
    assert {"token:bw", "token:flicker"} <= set(why) and bonus == 0
    assert name_signals("final_gameplay.png") == ([], 0.12)


def test_pixels_grid_and_colour(pics: dict[str, Path]) -> None:
    assert analyze_pixels(pics["suspects_overview.png"])["grid"] is True
    assert analyze_pixels(pics["lineup.png"])["grid"] is True
    for real in ("gameplay_lobby.png", "street_night.png", "bank_interior.png"):
        px = analyze_pixels(pics[real])
        assert px["grid"] is False, real
        assert px["sat"] > 0.15 and px["detail"] > 0.02
    assert analyze_pixels(pics["street_render.png"])["sat"] < 0.02
    assert analyze_pixels("does/not/exist.png") is None


def test_rank_sets_debug_artefacts_aside(pics: dict[str, Path]) -> None:
    evs = [ev(f"e{i}", path, t=float(i)) for i, path in enumerate(pics.values())]
    summary = rank_media(evs)
    junk = {Path(e.data["path"]).name: e.data["media_rank"]["why"] for e in evs if is_junk(e)}
    kept = {Path(e.data["path"]).name for e in evs if not is_junk(e)}
    assert kept == {"gameplay_lobby.png", "street_night.png", "bank_interior.png"}
    assert "grid" in junk["suspects_overview.png"] and "grid" in junk["lineup.png"]
    assert "greyscale" in junk["street_render.png"]
    assert "token:heads" in junk["g_heads_owen2.png"]
    assert any(w.startswith("aspect:") for w in junk["heads_strip.png"])
    assert "tiny" in junk["tiny.png"]
    assert summary["junk"] == len(junk) and set(summary["kept"]) == {e.id for e in evs if not is_junk(e)}
    for e in evs:                       # junk loses its weight; real shots keep theirs
        assert (e.weight <= 0.05) == is_junk(e)


def test_retries_keep_the_newest_and_duplicates_collapse(tmp_path: Path) -> None:
    for name, seed in (("shot_v2.png", 1), ("shot_v3.png", 2), ("other.png", 3)):
        scene(960, 540, seed).save(tmp_path / name)
    scene(960, 540, 3).save(tmp_path / "other_copy_final.png")      # the same frame saved again
    evs = [ev("e1", tmp_path / "shot_v2.png", 1), ev("e2", tmp_path / "shot_v3.png", 2),
           ev("e3", tmp_path / "other.png", 3), ev("e4", tmp_path / "other_copy_final.png", 4)]
    rank_media(evs)
    assert is_junk(evs[0]) and not is_junk(evs[1])                  # older retry set aside, newest kept
    assert is_junk(evs[2]) != is_junk(evs[3])                         # one of the two identical frames stays
    dup = evs[2] if is_junk(evs[2]) else evs[3]
    assert any(w.startswith("duplicate:") for w in dup.data["media_rank"]["why"])


def test_web_captures_are_never_junk(tmp_path: Path) -> None:
    scene(1440, 900, 9).convert("L").convert("RGB").save(tmp_path / "debug_grid_test.png")
    web = ev("e1", tmp_path / "debug_grid_test.png", kind="product_capture", target_kind="url",
             url="http://localhost:5173/")
    rank_media([web])
    assert not is_junk(web)


def test_presented_pictures_rank_higher(tmp_path: Path) -> None:
    scene(960, 540, 1).save(tmp_path / "a.png")
    scene(960, 540, 1).transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(tmp_path / "b.png")
    a, b = ev("e1", tmp_path / "a.png"), ev("e2", tmp_path / "b.png", delivered=True)
    rank_media([a, b])
    assert b.data["media_rank"]["score"] > a.data["media_rank"]["score"]
    assert b.data["media_rank"].get("presented") is True


def test_propagate_to_captured_copies(tmp_path: Path) -> None:
    sheet(2, 2, 320, 180).save(tmp_path / "contact_sheet.png")
    art = Event(id="e1", t=0, kind="artifact", tool="x", title="contact_sheet.png", summary="",
                data={"path": str(tmp_path / "contact_sheet.png"), "kind": "image"}, ok=True, weight=0.9)
    cap = Event(id="e2", t=1, kind="product_capture", tool="x", title="", summary="",
                data={"path": str(tmp_path / "contact_sheet.png"), "target_kind": "image", "source_ids": ["e1"]},
                ok=True, weight=0.9)
    rank_media([art])
    propagate([art, cap])
    assert is_junk(art) and is_junk(cap)


def test_rank_never_raises_on_missing_files() -> None:
    e = Event(id="e1", t=0, kind="screenshot", tool="x", title="", summary="",
              data={"path": "nope/missing_contact_sheet.png", "w": 1920, "h": 1080}, ok=True, weight=0.8)
    rank_media([e])
    assert is_junk(e) and "token:contact" in e.data["media_rank"]["why"]


def test_broken_pictures_never_become_heroes(tmp_path: Path) -> None:
    """Audit 2026-11-11: an empty render (``final.png``, 0 bytes) or an error page saved as ``logo.png`` used to rank
    as a real picture (and a hero name even first), so the film showed a blank card."""
    good = tmp_path / "e1_street.png"
    scene(960, 540, 3).save(good)
    empty = tmp_path / "e2_final.png"
    empty.write_bytes(b"")
    html = tmp_path / "e3_logo.png"
    html.write_bytes(b"<!doctype html><title>404 Not Found</title>")
    avif = tmp_path / "e4_shot.avif"                       # a format Pillow may lack is never called broken
    avif.write_bytes(b"\x00\x00\x00\x1cftypavif" + b"\x00" * 64)
    evs = [ev("e1", good, 1), ev("e2", empty, 2), ev("e3", html, 3), ev("e4", avif, 4, kind="image_generated")]
    out = rank_media(evs)
    assert is_junk(evs[1]) and is_junk(evs[2]) and "unreadable" in evs[1].data["media_rank"]["why"]
    assert not is_junk(evs[0]) and not is_junk(evs[3])
    assert out["kept"][0] == "e1" and "e2" not in out["kept"] and "e3" not in out["kept"]
