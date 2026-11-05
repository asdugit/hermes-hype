"""Cutout: backdrop model, soft key, hole protection, shadow removal, quality measurement."""
from __future__ import annotations

import time

from PIL import Image, ImageDraw
from synth import busy_frame, car_frame, iou

from showreel_core.capture.cutout import cutout, fit_background, render_background


def test_backdrop_models():
    flat, _ = car_frame(gradient=False, noise=0)
    m = fit_background(flat)
    assert m is not None and m.kind == "flat" and m.inliers > 0.95 and m.to_dict()["bg"] == "#d6d8db"
    grad, _ = car_frame(gradient=True)
    g = fit_background(grad)
    assert g is not None and g.kind == "gradient" and g.inliers > 0.95
    top, bottom = render_background(g, (64, 64)).getpixel((32, 1)), render_background(g, (64, 64)).getpixel((32, 62))
    assert top[0] > bottom[0] + 8          # the studio falloff is modelled
    assert fit_background(busy_frame()) is None


def test_red_car_on_grey_cutout_matches_ground_truth():
    frame, mask = car_frame()
    t0 = time.monotonic()
    rgba, q = cutout(frame)
    ms = (time.monotonic() - t0) * 1000
    assert rgba is not None and rgba.mode == "RGBA" and rgba.size == frame.size
    a = rgba.getchannel("A")
    assert iou(a, mask) > 0.97
    assert q.ok and q.grade == "good" and q.fragments == 1 and q.edge_touch == 0.0 and 0.1 < q.fg_fraction < 0.3
    assert a.getpixel((480, int(540 * 0.72) - int(540 * 0.27))) == 255     # window (backdrop-coloured) stays opaque
    assert a.getpixel((480, int(540 * 0.72 + 540 * 0.035))) < 40          # cast shadow under the body removed
    assert a.getpixel((5, 5)) == 0 and rgba.getpixel((5, 5))[:3] == (0, 0, 0)   # clean transparent pixels
    assert ms < 2000


def test_keep_shadow_option_keeps_the_shadow():
    frame, _ = car_frame()
    rgba, _ = cutout(frame, keep_shadow=True)
    assert rgba is not None and rgba.getchannel("A").getpixel((480, int(540 * 0.72 + 540 * 0.035))) > 128


def test_busy_background_gives_no_cutout():
    rgba, q = cutout(busy_frame())
    assert rgba is None and not q.ok and q.grade == "none" and "not uniform" in q.reason


def test_ui_screenshot_on_white_is_not_a_good_cutout():
    im = Image.new("RGB", (960, 540), "white")
    d = ImageDraw.Draw(im)
    for row in range(14):
        for col in range(4):
            d.rectangle([60 + col * 220, 40 + row * 34, 60 + col * 220 + 150, 52 + row * 34], fill=(40, 40, 50))
    _, q = cutout(im)
    assert q.grade in ("poor", "fair") and q.fragments > 10


def test_subject_cut_by_frame_edge_is_penalised():
    frame, _ = car_frame(x_shift=0.32)
    _, q = cutout(frame)
    clean = cutout(car_frame()[0])[1]
    assert q.edge_touch > 0 and q.score < clean.score
