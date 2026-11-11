"""Timing solver properties: beat grid, target fit, scene ranges, verbatim data, cues, splits."""
import itertools
import json
import math

import pytest
from story_synth import SESSIONS

from showreel_core.contracts import SCENE_RULES, SceneType, StoryScene
from showreel_core.story.facts import SessionFacts, code_lines, diff_rows
from showreel_core.story.heuristic import build_heuristic_storyboard
from showreel_core.story.options import StoryOptions
from showreel_core.story.rules import TTS_WORDS_PER_SECOND
from showreel_core.story.text import word_count
from showreel_core.story.timing import (
    END_HOLD_BARS,
    STRETCH,
    STRETCH_TYPES,
    solve_timeline,
)

T = SceneType
EPS = 1e-6
RICH = ("coding", "webapp", "huge")


def voice_for(sb):
    return {i: round(word_count(s.vo) / TTS_WORDS_PER_SECOND, 3) for i, s in enumerate(sb.scenes) if s.vo}


def solve(name, seconds, mode="product", bpm=120.0, voice=True, seed=1):
    events, stats = SESSIONS[name]()
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=seconds, mode=mode))
    tl = solve_timeline(sb, events, stats, voice_for(sb) if voice else {}, bpm, seconds, "16:9", 30, 1920, 1080,
                        seed, style="launch")
    return sb, tl, SessionFacts(events, stats)


def on_grid(t, step):
    return abs(t / step - round(t / step)) < 1e-6


@pytest.mark.parametrize("name", sorted(SESSIONS))
@pytest.mark.parametrize("mode", ("product", "making_of", "speedrun"))
@pytest.mark.parametrize("seconds,bpm", [(30, 120), (60, 128), (90, 100), (60, 150), (45, 72)])
def test_grid_ranges_and_fit(name, mode, seconds, bpm):
    _sb, tl, _ = solve(name, seconds, mode, bpm)
    beat = 60 / bpm
    hb, bar = 2 * beat, 4 * beat
    assert tl.mode == mode and tl.bpm == bpm
    assert tl.scenes and tl.scenes[0].t0 == 0
    for a, b in zip(tl.scenes, tl.scenes[1:]):
        assert abs(a.t1 - b.t0) < EPS
    for sc in tl.scenes:
        assert on_grid(sc.t0, hb) and on_grid(sc.t1, hb), (sc.type, sc.t0, sc.t1)
        lo, hi, _ = SCENE_RULES[sc.type]
        dur = sc.t1 - sc.t0
        voiced = sc.captions[-1].t1 + 0.4 if sc.captions else 0
        if dur > hi + EPS and voiced <= hi - EPS:
            # beyond the max only for narration (never cut), or when the film would otherwise stop short:
            # stretched holds and the end-card hold
            assert tl.dur <= seconds + hb + EPS, (sc.type, dur, tl.dur)
            assert dur <= _cap(sc.type, hi, bar) + hb + EPS, (sc.type, dur)
        assert dur >= min(lo, hb) - EPS
    assert on_grid(tl.dur, bar)
    assert abs(tl.dur - tl.scenes[-1].t1) < EPS
    assert tl.dur <= seconds + bar + EPS, (tl.dur, seconds)
    if tl.dur < seconds - bar - EPS:
        # Too little material for the target: allowed only when every scene is already at its
        # (grid-snapped) stretch cap and the end card holds as long as it may. Never padded with filler.
        for sc in tl.scenes[1:]:
            lo, hi, _ = SCENE_RULES[sc.type]
            cap = _cap(sc.type, hi, bar)
            assert sc.t1 - sc.t0 >= math.floor(cap / hb + EPS) * hb - EPS, (name, sc.type, sc.t1 - sc.t0)
    if name in RICH and seconds <= 60:
        # rich material fills the film; the end card no longer pads it (a 10 s END hold read as dead time)
        assert seconds - 2 * bar - EPS <= tl.dur <= seconds + bar + EPS, (tl.dur, seconds)


def _cap(st, hi, bar):
    if st == T.END:
        return hi + END_HOLD_BARS * bar
    return hi * STRETCH if st in STRETCH_TYPES else hi


@pytest.mark.parametrize("name", RICH)
@pytest.mark.parametrize("mode", ("product", "making_of", "speedrun"))
def test_narration_captions_and_cues_fit(name, mode):
    sb, tl, _ = solve(name, 60, mode)
    voice = voice_for(sb)
    beat = 60 / tl.bpm
    for sc in tl.scenes:
        assert sc.t0 - EPS <= sc.vo_t0 <= sc.t1
        src = sc.data["story_index"]
        if src in voice:
            assert sc.vo_t0 + voice[src] <= sc.t1 + EPS
            assert sc.captions and sc.captions[0].t0 >= sc.t0 - EPS and sc.captions[-1].t1 <= sc.t1 + EPS
            assert [c.t0 for c in sc.captions] == sorted(c.t0 for c in sc.captions)
    assert [c.t for c in tl.cues] == sorted(c.t for c in tl.cues)
    for cue in tl.cues:
        assert 0 <= cue.t < tl.dur and on_grid(cue.t, beat / 2), cue
    assert sum(c.sfx == "hit" for c in tl.cues) <= 1  # one hero impact per film
    push = [sc.i for sc in tl.scenes if sc.transition_in == "push"]
    assert all(b - a > 1 for a, b in itertools.pairwise(push))  # never two whooshes in a row


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


@pytest.mark.parametrize("name", sorted(SESSIONS))
@pytest.mark.parametrize("mode", ("product", "making_of", "speedrun"))
def test_resolved_content_is_verbatim(name, mode):
    sb, tl, facts = solve(name, 90, mode)
    for sc in tl.scenes:
        story = sb.scenes[sc.data["story_index"]]
        evs = [facts.by_id[r] for r in story.refs if r in facts.by_id]
        corpus = []
        for ev in evs:
            corpus += code_lines(ev) + [text for _, _, text in diff_rows(ev)]
            corpus += [str(x) for x in (ev.data or {}).values() if isinstance(x, str)]
            corpus += [str(x) for x in (ev.data or {}).get("output_lines") or []]
            corpus += [str(h.get("header", "")) for h in (ev.data or {}).get("hunks") or []]
        blob = "\n".join(corpus)
        if sc.type in (T.CODE, T.DIFF, T.TERMINAL, T.CALLOUT, T.PROBLEM):
            content = {k: v for k, v in sc.data.items() if k in ("lines", "hunks", "output", "cmd", "text")}
            for s in _strings(content):
                if s in ("+", "-", " "):
                    continue
                assert s in blob, (sc.type, s)
        if sc.type == T.CODE:
            ev = evs[0]
            start = sc.data["start"]
            assert sc.data["lines"] == code_lines(ev)[start - 1:start - 1 + len(sc.data["lines"])]
            assert len(sc.data["lines"]) <= 18
        if sc.type == T.DIFF:
            assert sum(len(h["lines"]) for h in sc.data["hunks"]) <= 24
        if sc.type == T.TERMINAL:
            assert len(sc.data["output"]) <= 12
        if sc.type == T.MONTAGE:
            for item in sc.data["items"]:
                ev = facts.by_id[item["id"]]
                shown = item["arg"].removeprefix("\u2026/").removesuffix("\u2026")   # display form: ellipsized
                assert shown in json.dumps(ev.data, ensure_ascii=False) or shown in ev.title
                assert "localhost" not in item["arg"] and "127.0.0.1" not in item["arg"]


@pytest.mark.parametrize("name", ("coding", "webapp", "huge", "bugfix"))
def test_speedrun_splits(name):
    _sb, tl, _ = solve(name, 60, "speedrun")
    beat = 60 / tl.bpm
    assert tl.splits
    for a, b in zip(tl.splits, tl.splits[1:]):
        assert b.session_t > a.session_t and b.film_t > a.film_t
    for sp in tl.splits:
        assert on_grid(sp.film_t, beat) and len(sp.label) <= 18 and 0 <= sp.film_t <= tl.dur
    end = next(sc for sc in tl.scenes if sc.type == T.END)
    assert end.data["pb_display"] and tl.splits[-1].session_t >= SESSIONS[name]()[1].duration_s - EPS
    assert sum(c.sfx == "appear" for c in tl.cues) >= len(tl.splits)
    _, product_tl, _ = solve(name, 60, "product")
    assert product_tl.splits == []


def test_long_narration_stretches_a_scene_but_stays_on_grid(coding):
    events, stats = coding
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=60))
    idx = next(i for i, s in enumerate(sb.scenes) if s.type == T.TITLE)
    tl = solve_timeline(sb, events, stats, {idx: 6.3}, 120, 60, "16:9", 30, 1920, 1080, 1)
    title = next(sc for sc in tl.scenes if sc.type == T.TITLE)
    assert title.t1 - title.t0 >= 6.3 + 0.7 - EPS > SCENE_RULES[T.TITLE][1]
    assert on_grid(title.t1, 1.0)


def test_too_many_scenes_drops_the_weakest(coding):
    events, stats = coding
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=90))
    tl = solve_timeline(sb, events, stats, voice_for(sb), 120, 30, "9:16", 30, 1080, 1920, 1)
    kept = {sc.type for sc in tl.scenes}
    assert {T.HOOK, T.TITLE, T.END} <= kept
    assert len(tl.scenes) < len(sb.scenes)
    assert abs(tl.dur - 30) <= 2 + EPS


def test_product_beats_outlive_build_scenes_when_cutting(coding):
    """A CLI's demo run is a product beat: the build story goes first when a product film is too long."""
    events, stats = coding
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=30))
    sb.scenes.insert(2, StoryScene(T.TERMINAL, ["e14"], "Point it at a folder and every month comes back sorted.",
                                   "Every month at a glance"))
    sb.scenes.insert(3, StoryScene(T.DIFF, ["e9"], "", "Refunds net out"))
    sb.scenes.insert(4, StoryScene(T.CODE, ["e6"], "", "The categorizer"))
    tl = solve_timeline(sb, events, stats, voice_for(sb), 110, 30, "16:9", 30, 1920, 1080, 1)
    shown = [sb.scenes[sc.data["story_index"]] for sc in tl.scenes]
    assert any(s.type == T.TERMINAL and s.refs == ["e14"] for s in shown)
    assert len(shown) < len(sb.scenes) and not any(s.type == T.CODE for s in shown)


def test_captions_only_and_determinism(coding):
    _, a, _ = solve("coding", 60, voice=False, seed=9)
    _, b, _ = solve("coding", 60, voice=False, seed=9)
    assert json.dumps(a.to_dict(), sort_keys=True) == json.dumps(b.to_dict(), sort_keys=True)
    assert any(sc.captions for sc in a.scenes)


def test_unresolvable_scenes_are_skipped(coding):
    events, stats = coding
    sb = build_heuristic_storyboard(events, stats, StoryOptions(seconds=30))
    sb.scenes.insert(2, StoryScene(T.CODE, ["e99"], "", "ghost"))
    sb.scenes.insert(3, StoryScene(T.TERMINAL, ["e4"], "", "wrong kind"))
    tl = solve_timeline(sb, events, stats, {}, 120, 30, "16:9", 30, 1920, 1080, 1)
    assert all(sc.label not in ("ghost", "wrong kind") for sc in tl.scenes)


def test_stats_and_images_resolve(coding):
    _sb, tl, _ = solve("coding", 60)
    stats = next(sc for sc in tl.scenes if sc.type == T.STATS)
    assert all(row["value"] > 0 and row["display"] for row in stats.data["stats"])
    feature = next((sc for sc in tl.scenes if sc.type == T.FEATURE), None)
    if feature is not None:
        x, y, w, h = feature.data["bbox"]
        assert 0 <= x <= 1 and 0 <= y <= 1 and x + w <= 1 + EPS and y + h <= 1 + EPS
        assert feature.data["image"]["path"]
    assert math.isclose(sum(sc.t1 - sc.t0 for sc in tl.scenes), tl.dur)
