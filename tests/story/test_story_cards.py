"""Non-web pictures (game/app screenshots, renders, image files) are cards, never a fake browser; debug artefacts
set aside by session.mediarank never reach a film (validate swaps them for the best unused real shot)."""
from __future__ import annotations

from pathlib import Path

import pytest

from showreel_core.contracts import Event, Product, SceneType, Stats, Storyboard, StoryScene
from showreel_core.capture.crops import is_safe
from showreel_core.session.mediarank import rank_media
from showreel_core.story.facts import SessionFacts, image_of, picture_frame
from showreel_core.story.timing import solve_timeline
from showreel_core.story.validate import validate_storyboard

T = SceneType
PIL = pytest.importorskip("PIL")


def _ev(i: int, ekind: str, path: str = "", **data) -> Event:
    return Event(f"e{i}", 100.0 + i, ekind, "x", Path(path).name or ekind, "", {"path": path, **data}, weight=0.8)


def test_frames_by_source() -> None:
    web = _ev(1, "product_capture", "cap/viewport.png", url="http://127.0.0.1:5173/", target_kind="url",
              kind="viewport")
    html = _ev(2, "product_capture", "cap/index.png", url="file:///p/index.html", target_kind="html")
    file_img = _ev(3, "product_capture", "cap/image.jpg", url="shots/lobby.jpg", target_kind="image", kind="image")
    legacy_web = _ev(4, "product_capture", "cap/v.png", url="http://localhost:3000/", kind="viewport")
    game = _ev(5, "screenshot", "shots/game.png")
    page_shot = _ev(6, "screenshot", "shots/page.png", url="https://example.com/app")
    render = _ev(7, "image_generated", "renders/hero.png")
    assert [picture_frame(e) for e in (web, html, file_img, legacy_web, game, page_shot, render)] == \
        ["browser", "browser", "card", "browser", "card", "browser", "card"]
    assert image_of(game)["frame"] == "card" and image_of(web)["frame"] == "browser"


def _scene_png(path: Path, w: int, h: int, seed: int) -> None:
    from tests.session.test_mediarank import scene
    scene(w, h, seed).save(path)


@pytest.fixture()
def game_session(tmp_path: Path) -> list[Event]:
    from tests.session.test_mediarank import sheet
    _scene_png(tmp_path / "lobby_gameplay.png", 1920, 1080, 1)
    _scene_png(tmp_path / "street_gameplay.png", 1920, 1080, 2)
    sheet(5, 1, 360, 360, seed=40).save(tmp_path / "g_heads_owen5.png")     # the strip the old film cut at the eyes
    sheet(2, 2, 480, 270, seed=50).save(tmp_path / "contact_left.png")
    events = [
        Event("e0", 0.0, "user_prompt", "", "", "", {"text": "build a detective game in roblox"}),
        _ev(1, "screenshot", str(tmp_path / "lobby_gameplay.png")),
        _ev(2, "screenshot", str(tmp_path / "g_heads_owen5.png")),
        _ev(3, "screenshot", str(tmp_path / "contact_left.png")),
        _ev(4, "screenshot", str(tmp_path / "street_gameplay.png")),
    ]
    rank_media(events)
    return events


def _sb(scenes: list[StoryScene]) -> Storyboard:
    return Storyboard(title="Casefile", tagline="Every clue proves the culprit", cta="", mode="product",
                      product=Product(name="Casefile", kind="game", features=["Twelve authored suspects"]),
                      scenes=scenes)


def test_junk_refs_are_swapped_for_real_shots(game_session: list[Event]) -> None:
    facts = SessionFacts(game_session, Stats(duration_s=3600), "")
    sb = _sb([
        StoryScene(T.HOOK, ["e3"], "", "Read the clues"),
        StoryScene(T.TITLE, [], "", "Casefile"),
        StoryScene(T.FEATURE, ["e2"], "", "Twelve authored suspects",
                   {"feature": "Twelve authored suspects", "bbox": [0.04, 0.4, 0.6, 0.6]}),
        StoryScene(T.END, [], "", ""),
    ])
    res = validate_storyboard(sb, facts, 30, "product")
    refs = {s.type: s.refs for s in res.storyboard.scenes}
    assert refs[T.HOOK][0] in ("e1", "e4") and refs[T.FEATURE][0] in ("e1", "e4")
    assert refs[T.HOOK][0] != refs[T.FEATURE][0]                     # a swap never repeats a picture
    assert any(i.code == "debug_media" for i in res.issues)
    assert image_of(game_session[2]) is None and image_of(game_session[3]) is None


def test_no_padding_when_real_shots_run_out(game_session: list[Event]) -> None:
    facts = SessionFacts(game_session, Stats(duration_s=3600), "")
    sb = _sb([
        StoryScene(T.SCREEN, ["e1"], "", "The lobby"),
        StoryScene(T.SCREEN, ["e4"], "", "The street"),
        StoryScene(T.FEATURE, ["e2"], "", "Twelve authored suspects", {"feature": "Twelve authored suspects"}),
        StoryScene(T.TITLE, [], "", "Casefile"),
        StoryScene(T.END, [], "", ""),
    ])
    res = validate_storyboard(sb, facts, 30, "product")
    shown = [s.refs[0] for s in res.storyboard.scenes if s.type in (T.SCREEN, T.FEATURE, T.HOOK)]
    assert sorted(shown) == ["e1", "e4"]                               # the junk FEATURE is dropped, not padded


def test_card_shots_get_safe_crops_and_dissolves(game_session: list[Event]) -> None:
    sb = _sb([
        StoryScene(T.TITLE, [], "", "Casefile"),
        StoryScene(T.FEATURE, ["e1"], "", "Twelve authored suspects",
                   {"feature": "Twelve authored suspects", "bbox": [0.05, 0.42, 0.9, 0.15]}),
        StoryScene(T.SCREEN, ["e4"], "", "The street", {"bbox": [0.0, 0.45, 1.0, 0.1]}),
        StoryScene(T.END, [], "", ""),
    ])
    tl = solve_timeline(sb, game_session, Stats(duration_s=3600), {}, 120.0, 30, "16:9", 30, 1920, 1080, 1)
    shots = {s.type: s for s in tl.scenes}
    for typ in (T.FEATURE, T.SCREEN):
        d = shots[typ].data
        assert d["image"]["frame"] == "card"
        assert is_safe(d["bbox"], 1920, 1080), d["bbox"]               # never the thin band the model asked for
    assert shots[T.SCREEN].transition_in == "match"                   # picture to picture: a cross-dissolve
    feat_t = (shots[T.FEATURE].t0, shots[T.FEATURE].t1)
    assert not [c for c in tl.cues if c.sfx == "click" and feat_t[0] <= c.t < feat_t[1]]   # no cursor, no click
