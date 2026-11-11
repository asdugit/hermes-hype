"""Device screens: the product's capture always fits INSIDE the bezel with its own aspect, phones get the
mobile-viewport capture.

Regression: an element crop (a portrait card, 1072x1432) was cover-fitted onto the 16:10 laptop screen, so the UI
was magnified past the screen (timer ring cut by the bezel, the button cut at the keyboard deck), and a phone next
to the laptop showed the DESKTOP capture cropped mid-word because the job never got the mobile capture.

Pure maths + host asset planning run everywhere; the real render (``--runslow``) measures it in pixels: a synthetic
capture with four coloured corner markers must show all four markers on screen (nothing cropped) and the letterbox
must be the capture's page colour (no smeared edge pixels).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from showreel_core.blender import film as bf

REPO = Path(__file__).resolve().parents[2]
KIT = REPO / "blender_kits"


def _specs():
    from blender_kits.lib.device import SPECS

    return {k: (v["disp_w"], v["disp_h"]) for k, v in SPECS.items()}


def _shown(win, img_w, img_h, scr_w, scr_h):
    """(fraction of the image width, of the image height) visible on screen; x/y metres-per-pixel ratio."""
    x0, y0, sx, sy = win
    vis_w = max(0.0, min(1.0, x0 + sx) - max(0.0, x0))
    vis_h = max(0.0, min(1.0, y0 + sy) - max(0.0, y0))
    return vis_w, vis_h, (scr_w / (sx * img_w)) / (scr_h / (sy * img_h))


IMAGES = {"element_card": (1072, 1432), "desktop_169": (1920, 1080), "desktop_1610": (1440, 900),
          "mobile": (390, 844), "square": (800, 800), "ultrawide": (2560, 1080), "banner": (1200, 300),
          "tall_card": (600, 1100)}


@pytest.mark.parametrize("img", sorted(IMAGES))
@pytest.mark.parametrize("kind", ["laptop", "phone", "tablet", "monitor"])
def test_screen_window_never_magnifies_past_the_bezel(kind, img):
    from blender_kits.lib.materials import fit_window

    sw, sh = _specs()[kind]
    iw, ih = IMAGES[img]
    if ih >= 2 * iw:
        pytest.skip("long pages scroll (cover, top first): test_long_pages_and_matching_captures_still_cover")
    win, used = fit_window(iw, ih, sw, sh)
    vis_w, vis_h, aspect = _shown(win, iw, ih, sw, sh)
    assert aspect == pytest.approx(1.0, rel=1e-6), "image is stretched"
    assert win[2] > 0 and win[3] > 0, "mirrored"
    # at most 12 % of the capture may be trimmed (a 16:9 page on a 16:10 laptop); anything more is letterboxed
    assert vis_w >= 0.88 - 1e-9 and vis_h >= 0.88 - 1e-9, (kind, img, used, win)


def test_element_card_on_laptop_is_letterboxed_whole():
    from blender_kits.lib.materials import fit_window

    sw, sh = _specs()["laptop"]
    win, used = fit_window(1072, 1432, sw, sh)
    assert used == "contain"
    x0, y0, sx, sy = win
    assert y0 == pytest.approx(0.0) and sy == pytest.approx(1.0)       # full height
    assert x0 < 0 and x0 + sx > 1                                     # bands left and right


def test_desktop_on_phone_is_whole_not_a_cropped_column():
    from blender_kits.lib.materials import fit_window

    sw, sh = _specs()["phone"]
    win, used = fit_window(1920, 1080, sw, sh)
    assert used == "contain" and win[0] == pytest.approx(0.0) and win[2] == pytest.approx(1.0)


def test_long_pages_and_matching_captures_still_cover():
    from blender_kits.lib.materials import fit_window

    lw, lh = _specs()["laptop"]
    pw, ph = _specs()["phone"]
    assert fit_window(1440, 900, lw, lh)[1] == "cover"                 # exact 16:10
    assert fit_window(1920, 1080, lw, lh)[1] == "cover"                # trims 10 %: fills the screen
    assert fit_window(390, 844, pw, ph)[1] == "cover"                  # mobile viewport on a phone
    win, used = fit_window(1440, 6000, lw, lh)                         # long page: top shows, scenes scroll it
    assert used == "cover" and win[1] + win[3] == pytest.approx(1.0) and win[2] == pytest.approx(1.0)
    assert fit_window(1440, 6000, lw, lh, fit="contain")[1] == "contain"


# ------------------------------------------------------------------ host: the job gets the mobile capture


def _png(p: Path) -> Path:
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return p


def test_device_job_gets_the_capture_stage_mobile_twin(tmp_path):
    cap = tmp_path / "capture" / "web" / "html_01_index"
    cap.mkdir(parents=True)
    desk = _png(cap / "desktop_1920x1080.png")
    _png(cap / "mobile_full_390.jpg")
    mob = _png(cap / "mobile_390x844.png")
    used = {"m0_desktop_1920x1080": {"kind": "image", "path": str(desk)}}
    tw = bf.device_twins(KIT / "device" / "device_trio.py", used, used)
    assert tw == {"mobile_390x844": {"kind": "image", "path": str(mob.resolve())}}
    # other kits never get it; a shot that already names a mobile capture keeps its own
    assert bf.device_twins(KIT / "studio" / "product_hero.py", used, used) == {}
    mine = {**used, "m3_mobile_390x844": {"kind": "image", "path": str(mob)}}
    assert bf.device_twins(KIT / "device" / "device_hero.py", mine, mine) == {}


def test_device_job_prefers_the_films_own_mobile_asset(tmp_path):
    desk = _png(tmp_path / "shot.png")
    mob = _png(tmp_path / "phone.png")
    used = {"desk": {"kind": "image", "path": str(desk)}}
    every = {**used, "m3_mobile_390x844": {"kind": "image", "path": str(mob)},
             "m4_mobile_full_390": {"kind": "image", "path": str(mob)}}
    assert list(bf.device_twins(KIT / "device" / "device_end.py", used, every)) == ["m3_mobile_390x844"]
    assert bf.device_twins(KIT / "device" / "device_end.py", used, used) == {}   # nothing next to it either


def test_render_film_shots_passes_the_mobile_twin_to_device_jobs(tmp_path):
    """Through the real planner (fake command): the device job.json lists the mobile capture."""
    import json

    cap = tmp_path / "cap"
    cap.mkdir()
    desk = _png(cap / "desktop_1920x1080.png")
    _png(cap / "mobile_390x844.png")
    film = {"version": 1, "fps": 30, "size": [320, 180], "dur": 1.0, "seed": 1, "title": "t",
            "assets": {"desk": {"src": str(desk)}},
            "shots": [{"id": "a", "t0": 0, "t1": 1.0, "scene": "blender:device/device_trio",
                       "params": {"media": "desk"}}], "transitions": [], "overlays": [], "cues": []}
    def command(job_path: Path) -> list[str]:
        return [sys.executable, "-c", "import sys; sys.exit(3)"]

    out = bf.render_film_shots(film, tmp_path / "job", blender=Path(sys.executable), tier="preview",
                               benchmark=False, command=command)
    assert not out.ok                                   # the fake Blender fails; we only inspect the plan
    job = json.loads(next((tmp_path / "job").rglob("job.json")).read_text(encoding="utf-8"))
    assert "mobile_390x844" in job["assets"] and job["assets"]["desk"]["path"].endswith("desktop_1920x1080.png")


# ------------------------------------------------------------------ real Blender: measured in pixels

MARK = {"tl": (255, 0, 0), "tr": (0, 200, 0), "bl": (0, 60, 255), "br": (255, 220, 0)}
PAGE = (40, 44, 52)


def _marker_capture(path: Path, w: int, h: int) -> Path:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (w, h), PAGE)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((w * 0.12, h * 0.1, w * 0.88, h * 0.9), radius=w * 0.05, fill=(236, 236, 240))
    m = max(8, min(w, h) // 7)
    for key, (x, y) in {"tl": (0, 0), "tr": (w - m, 0), "bl": (0, h - m), "br": (w - m, h - m)}.items():
        d.rectangle((x, y, x + m - 1, y + m - 1), fill=MARK[key])
    im.save(path)
    return path


def _count(im, rgb, tol=40) -> int:
    flat = getattr(im, "get_flattened_data", None)
    px = flat() if flat else im.getdata()
    return sum(1 for p in px if all(abs(a - b) <= tol for a, b in zip(p, rgb)))


@pytest.fixture(scope="module")
def blender():
    sys.path.insert(0, str(Path(__file__).parent))
    from showreel_core.blender import locate as loc

    found = loc.locate()
    if not found.ok:
        pytest.skip(getattr(found, "message", "Blender not found"))
    return found


def _render(blender, tmp_path, scene: str, res, params, assets, dur=1.0, last=False):
    from devguard import dev_lock, min_free_gb

    from showreel_core.blender import runner

    f = int(round(dur * 30)) if last else 1
    job = runner.make_job(KIT / f"{scene}.py", tmp_path / scene.replace("/", "_"), dur=dur, fps=30, res=res,
                          params=params, tier="preview", frames=[f], assets=assets)
    r = runner.run_job(job, blender, lock=lambda: dev_lock("hype-device-fit"), min_free_gb=min_free_gb(),
                       timeout_s=600)
    assert r.ok, (r.error, r.traceback[-2000:] if r.traceback else "")
    from PIL import Image

    return Image.open(runner.frame_path(job, f)).convert("RGB")


@pytest.mark.slow
def test_real_render_card_on_laptop_shows_all_four_corners(blender, tmp_path):
    card = _marker_capture(tmp_path / "element_card.png", 536, 716)
    im = _render(blender, tmp_path, "device/device_feature", (480, 270),
                 {"image": "card", "bbox": [0.2, 0.2, 0.6, 0.6], "device": "laptop", "angle": 0},
                 {"card": {"kind": "image", "path": str(card)}})
    counts = {k: _count(im, c) for k, c in MARK.items()}
    assert all(n >= 3 for n in counts.values()), f"a corner of the capture is cropped off the screen: {counts}"


@pytest.mark.slow
def test_real_render_desktop_on_phone_is_whole(blender, tmp_path):
    desk = _marker_capture(tmp_path / "desktop_1600x900.png", 1600, 900)
    im = _render(blender, tmp_path, "device/device_hero", (360, 640),
                 {"media": "desk", "device": "phone", "reveal": False, "screen_on": 0.0, "orbit_deg": 0.0,
                  "entrance": "turn"}, {"desk": {"kind": "image", "path": str(desk)}}, last=True)
    im.save(tmp_path / "phone_last.png")
    counts = {k: _count(im, c, tol=60) for k, c in MARK.items()}
    assert all(n >= 1 for n in counts.values()), f"the desktop capture is cropped on the phone: {counts}"
    # the bands above and below the capture are its page colour (~70 % of the phone screen), not black/streaks
    assert _count(im, PAGE, tol=8) >= 4000, "letterbox is not the capture's page colour"
