"""Pure-Python tests for the meadow kit: camera smoothness, flyer no-dying rules, the oner layout (both aspects).

Runs without Blender (the planning math is bpy-free).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from blender_kits.lib import camera as C  # noqa: E402
from blender_kits.lib import flyers as Fl  # noqa: E402
from blender_kits.lib.meadow import Terrain  # noqa: E402
from blender_kits.meadow import oner  # noqa: E402

FPS = 30


def test_spline_is_c2_through_beats():
    sp = C.Spline1D([0, 1, 2.5, 4], [0, 2, 1, 3])
    for t, y in ((0, 0), (1, 2), (2.5, 1), (4, 3)):
        assert sp(t) == pytest.approx(y, abs=1e-9)
    # first and second derivatives continuous across a knot
    e = 1e-4
    for k in (1.0, 2.5):
        d_l = (sp(k) - sp(k - e)) / e
        d_r = (sp(k + e) - sp(k)) / e
        assert d_l == pytest.approx(d_r, abs=1e-2)
        a_l = (sp(k) - 2 * sp(k - e) + sp(k - 2 * e)) / e ** 2
        a_r = (sp(k + 2 * e) - 2 * sp(k + e) + sp(k)) / e ** 2
        assert a_l == pytest.approx(a_r, rel=0.05, abs=0.05)


def test_clamped_start_velocity():
    sp = C.Spline1D([0, 2, 4], [0, 3, 5], v0=1.25)
    assert sp.d(0.0) == pytest.approx(1.25, abs=1e-6)


def test_smoothness_flags_a_pop():
    pos = [(f * 0.1, 0.0, 0.0) for f in range(60)]
    assert C.smoothness(pos)["ok"]
    popped = pos[:30] + [(p[0] + 0.5, 0.0, 0.0) for p in pos[30:]]
    rep = C.smoothness(popped)
    assert not rep["ok"] and rep["vel_jumps"]


def test_smoothness_flags_a_fast_pan():
    fwd = [(math.sin(math.radians(5 * f)), math.cos(math.radians(5 * f)), 0.0) for f in range(30)]
    rep = C.smoothness([(0, 0, 0)] * 30, fwd)
    assert rep["pan_fast"]


@pytest.mark.parametrize("name", ["crane", "dolly", "orbit", "push"])
def test_presets_are_smooth(name):
    if name == "crane":
        beats = C.crane(0, 6, (0, -10, 1.5), (0, 0, 1.5))
    elif name == "dolly":
        beats = C.dolly(0, 6, (0, -10, 1.5), (0, -4, 1.5), (0, 0, 1.5))
    elif name == "orbit":
        beats = C.orbit(0, 8, (0, 0, 0), 9.0, 180, 300, 2.0)
    else:
        beats = C.push(0, 5, (0, -12, 1.6), (0, 0, 1.2), 4.0)
    mv = C.Move(beats)
    S = mv.sample(FPS, 6 * FPS)
    rep = C.smoothness([s.pos for s in S], [s.fwd for s in S])
    assert rep["ok"], rep


def test_rack_focus_is_continuous():
    mv = C.Move([C.Beat(0, (0, -10, 1.5), (0, 0, 1.5)), C.Beat(4, (2, -8, 1.5), (0, 0, 1.5))])
    mv.focus_on([(0.0, (0, 0, 1.5)), (1.5, (0, 20, 3)), (3.0, 1.0)], dur=0.8)
    S = mv.sample(FPS, 4 * FPS)
    jumps = [abs(S[i + 1].focus - S[i].focus) for i in range(len(S) - 1)]
    assert max(jumps) < 2.5          # 20 m pull in 0.8 s; continuous (no single-frame snap)
    assert jumps[0] < 0.05 and jumps[-1] < 0.05


GROUND = Terrain(seed=7)


@pytest.mark.parametrize("name", Fl.PRESETS)
def test_flyer_presets_never_die(name):
    fl = Fl.preset(name, t0=1.0, t1=7.0, origin=(0, -12, GROUND(0, -12) + 1.5), depth=30, height=6,
                   ground=GROUND)
    if fl.mode == "drive":
        fl.points = [(x, y, GROUND(x, y)) if i < 3 else (x, y, z + GROUND(x, y)) for i, (x, y, z) in enumerate(fl.points)]
    poses = Fl.plan(fl, FPS, 9 * FPS, ground=GROUND)
    assert Fl.validate(fl, poses, GROUND) == []
    rep = C.smoothness([p.pos for p in poses])
    assert not rep["vel_jumps"], rep


def test_exit_keeps_momentum_after_t1():
    fl = Fl.preset("arc_across", t0=0.0, t1=4.0, depth=30, height=6)
    poses = Fl.plan(fl, FPS, 6 * FPS)
    after = [p.speed for p in poses if p.t > 4.0]
    assert after and min(after) >= 0.9 * fl.v1


def test_wheel_spin_capped_and_forward():
    fl = Fl.preset("pass_by_camera", t0=0.0, t1=3.0, depth=30, height=6)
    poses = Fl.plan(fl, FPS, 3 * FPS)
    steps = [poses[i + 1].wheel - poses[i].wheel for i in range(len(poses) - 1)]
    assert all(s < 0 for s in steps[1:])                      # rolling forward
    assert max(abs(s) for s in steps) <= fl.spin_cap + 1e-9   # no strobing


def test_slowdown_is_reported():
    fl = Fl.Flight("dying", [(0, 0, 10), (10, 0, 10), (20, 0, 10)], 0.0, 4.0, v0=30.0, v1=1.0)
    errs = Fl.validate(fl, Fl.plan(fl, FPS, 4 * FPS))
    assert any("momentum" in e or "slows" in e for e in errs)


def test_sinking_exit_is_reported():
    fl = Fl.Flight("sink", [(0, 0, 30), (10, 0, 20), (15, 0, 2)], 0.0, 3.0, v0=8.0, v1=10.0)
    errs = Fl.validate(fl, Fl.plan(fl, FPS, 3 * FPS))
    assert any("sinking" in e for e in errs)


@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
def test_oner_layout(aspect):
    L = oner.Layout(aspect)
    mv = L.rig()
    n = int(L.length * FPS)
    S = mv.sample(FPS, n)
    rep = C.smoothness([s.pos for s in S], [s.fwd for s in S])
    assert rep["ok"], rep
    for f, ps in zip(L.flights, L.poses(FPS, n, 0.0)):
        errs = Fl.validate(f, ps, L.hf, clearance=-0.35)
        assert errs == [], errs
        dmin = min(math.dist(p.pos, s.pos) for p, s in zip(ps, S))
        assert dmin > 2.8, (f.name, dmin)                   # nothing flies through the lens
        assert min(math.dist(p.pos, L.head) for p in ps) > 4.0   # nothing flies through her
    # the camera never dips into the ground
    assert min(s.pos[2] - L.hf(s.pos[0], s.pos[1]) for s in S) > 0.45      # low angle among the flowers


def test_oner_continuation_matches():
    """The reveal shot + the continuation (t_offset) sample the same move."""
    L = oner.Layout("16:9", reveal=True)
    mv = L.rig()
    a = mv.eval(1.8 + 3.0)
    b = mv.sample(FPS, 200, t_offset=1.8)[90]
    assert a.pos == pytest.approx(b.pos) and a.focus == pytest.approx(b.focus)


@pytest.mark.parametrize("aspect", ["16:9", "9:16"])
def test_oner_framing_busy_and_readable(aspect):
    """A car is readable (>= 12 % of the frame width, inside the frame or a fast pass-by) almost all the time once
    the petals clear, the sky is busy (dozens of cars), and the figure is big in the opener (16:9)."""
    L = oner.Layout(aspect, reveal=True)
    rows = L.framing(FPS, 0.0, L.length, step=3, occlusion=False)
    after = [r for r in rows if r["t"] >= 1.5]
    share = sum(1 for r in after if r["readable"]) / len(after)
    assert share > 0.88, share
    counts = sorted(len(r["cars"]) for r in rows)
    assert counts[len(counts) // 2] >= 12, counts
    assert len(L.flights) >= 60
    if aspect == "16:9":
        assert rows[0]["fig"]["h"] > 0.4


def test_oner_windows_toggle_offscreen():
    """Cars appear/vanish only on frames where they are off-screen; far streams are always there."""
    L = oner.Layout("16:9", reveal=True)
    n = 200
    wins = L.windows(FPS, n, 3.0)
    rows = L.framing(FPS, 3.0, 3.0 + (n - 1) / FPS, occlusion=False)
    for f, (a, b) in zip(L.flights, wins):
        if a > 0:
            assert f.name not in rows[a]["cars"], f.name
        if b < n - 1:
            assert f.name not in rows[b]["cars"], f.name
