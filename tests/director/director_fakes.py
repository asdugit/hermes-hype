"""Fakes and fixtures for Director tests: a scripted model, a scripted renderer, a tiny kit + audio catalog."""
from __future__ import annotations

import copy
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest

from showreel_core.contracts import Product
from showreel_core.director.backend import Preview, ShotError, write_scenes
from showreel_core.director.catalog import build_catalog
from showreel_core.director.llm import LlmReply
from showreel_core.director.types import Brief, MediaAsset

KIT_MD = """# Fake kit

Pixel and nature scenes for tests, plus a title card.

- `kit:fake/walk` - a party walks a dungeon corridor toward a boss door.
- `kit:fake/field` - anime flower field at sunset with flying product media.
- `kit:fake/title` - big title card with product name and CTA.
- `kit:fake/petal-bloom` - pixels burst into petals.
"""

KIT_JS = """
import { sr } from '../../runtime/showreel.js';
sr.defineScene('kit:fake/walk', {
  layer: '2d', describe: 'Party walks a dungeon corridor toward a boss door.',
  params: { party: { type: 'list', default: [] }, media: { type: 'asset', default: null, doc: 'boss media' } },
  render(ctx, t, p) {}
});
export const field = { id: 'kit:fake/field', def: { layer: '2d',
  describe: 'Anime flower field at sunset with flying product media.', params: FIELD, render() {} } };
const FIELD = { flyers: { type: 'list', default: [] }, time: { type: 'string', default: 'sunset' } };
sr.defineScene('kit:fake/title', { layer: 'dom', describe: 'Title card.', params: { text: { type: 'string' },
  sub: { type: 'string', default: '' } }, render() {} });
sr.defineTransition('kit:fake/petal-bloom', { kind: 'canvas', render() {} });
"""


def _bars(style: str, bed: str, bpm: float) -> dict[str, Any]:
    return {"style": style, "beds": [{"id": bed, "style": style, "title": bed.upper(), "bpm": bpm, "bar_s": 240 / bpm,
                                      "duration_s": 60.0, "notes": f"{style} test bed",
                                      "sections": [{"name": "intro", "start_bar": 0, "bars": 4}]}]}


SFX = {"version": 1, "sounds": {
    "hit": {"class": "hero", "tags": ["reveal"], "files": [{"file": "hit_1.ogg", "dur": 0.8}]},
    "riser": {"class": "hero", "tags": ["build"], "files": [{"file": "riser_1.ogg", "dur": 2.4}]},
    "click": {"class": "foley", "tags": ["ui"], "files": [{"file": "click_1.ogg", "dur": 0.07}]},
    "whoosh_short": {"class": "foley", "tags": ["transition"], "files": [{"file": "w.ogg", "dur": 0.5}]},
}}


def png(color: tuple[int, int, int] = (200, 30, 30), size: tuple[int, int] = (96, 54)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def env(tmp_path: Path) -> dict[str, Any]:
    """Kit dir, audio dir, library dir, a product asset with a thumbnail, a brief and a catalog."""
    kits = tmp_path / "kits" / "fake"
    kits.mkdir(parents=True)
    (kits / "KIT.md").write_text(KIT_MD, encoding="utf-8")
    (kits / "kit.js").write_text(KIT_JS, encoding="utf-8")
    audio = tmp_path / "audio"
    for style, bed, bpm in (("pixel", "pixel_a", 150.0), ("cinematic", "cinematic_a", 80.0)):
        d = audio / "beds" / style
        d.mkdir(parents=True)
        (d / "bars.json").write_text(json.dumps(_bars(style, bed, bpm)), encoding="utf-8")
    (audio / "sfx").mkdir(parents=True)
    (audio / "sfx" / "sfx.json").write_text(json.dumps(SFX), encoding="utf-8")
    thumb = tmp_path / "car-poster.png"
    thumb.write_bytes(png())
    car = MediaAsset("car", "video", str(tmp_path / "car.mp4"), 1280, 720, 6.0, 30.0, str(thumb),
                     "a glossy red car driving left to right")
    brief = Brief("pixel but transition into a different style mid way through, goal is to sell the product",
                  product=Product(name="Red Car", one_liner="A red car."), assets=[car], seconds=45.0)
    lib = tmp_path / "library"
    cat = build_catalog(kits_dir=tmp_path / "kits", audio_dir=audio, library_dir=lib, assets=[car])
    return {"tmp": tmp_path, "brief": brief, "catalog": cat, "library": lib, "job": tmp_path / "job", "car": car,
            "kits": tmp_path / "kits", "audio": audio}


# ------------------------------------------------------------------------------------ canned replies

TREATMENT = {
    "title": "Red Car", "logline": "A pixel party meets its boss: the car. One click on BUY and the world blooms.",
    "audience": "drivers", "selling_point": "the car is the most beautiful thing in any world",
    "requirements": [{"text": "pixel", "how": "act 1 is pixel art"},
                     {"text": "transition into a different style mid way", "how": "petal bloom into an anime field"},
                     {"text": "sell the product", "how": "car is the boss and the hero of act 2"}],
    "signature_moment": "the cursor picks BUY instead of FIGHT",
    "hook": {"t": 1.2, "what": "the boss silhouette glows red at the end of the corridor"},
    "emotional_arc": "tension -> release -> desire",
    "acts": [{"name": "Dungeon", "world": "pixel dungeon", "style": "pixel", "duration": 20, "beats": ["walk", "boss"],
              "product_role": "boss", "palette": ["#1a1c2c", "#b13e53"]},
             {"name": "Field", "world": "anime flower field", "style": "painterly", "duration": 24,
              "beats": ["bloom", "cars fly"], "product_role": "hero", "palette": ["#f6c38e"]}],
    "transitions": [{"from_act": "Dungeon", "to_act": "Field", "idea": "petal burst", "motivation": "BUY click"}],
    "music_plan": [{"bed": "pixel_a", "from_s": 0, "to_s": 20, "why": "chiptune"},
                   {"bed": "nope_bed", "from_s": 20, "to_s": 45, "why": "x"}],
    "stings": [{"sting": "riser", "t": 18.5, "why": "turn"}],
    "asset_plan": [{"asset": "car", "use": "boss portrait and flyers"}],
    "payoff": "cars fly over the field", "cta": "Buy the Red Car", "risks": ["pixelated car unreadable"],
}

SPEC = ("480x270 pixel battle. Layers: dungeon wall, floor, party bottom-left, boss top-right: the car media "
        "pixelated to 160 px wide with a 1 px outline and an HP bar 'RED CAR LV 99'. Beats: 0-1.5 s boss idle bob; "
        "1.5-2.1 s wind-up; 2.1 s blade flies left; 2.4 s hit: party flashes red, shake, damage number -42; "
        "4.0 s menu FIGHT ITEM BUY RUN; cursor moves to BUY at 6.0 s; click at 7.2 s; palette #1a1c2c #b13e53.")

FILM = {"film": {
    "title": "Red Car",
    "shots": [
        {"id": "walk", "t0": 0, "t1": 6, "scene": "kit:fake/walk", "res": [480, 270],
         "params": {"party": ["knight", "mage"], "media": "car"}},
        {"id": "boss", "t0": 6, "t1": 20, "scene": "custom:boss-battle", "res": [480, 270],
         "params": {"boss_media": "car", "pick": "BUY"}},
        {"id": "field", "t0": 20, "t1": 45, "scene": "kit:fake/field", "res": None,
         "params": {"flyers": [{"media": "car", "path": "descend"}], "time": "sunset"}}],
    "transitions": [{"from": "boss", "to": "field", "type": "kit:fake/petal-bloom", "t": 19.4, "dur": 1.2}],
    "overlays": [{"id": "title", "t0": 41, "t1": 45, "scene": "kit:fake/title", "params": {"text": "RED CAR"}}],
    "music": [{"bed": "pixel_a", "t0": 0, "t1": 20}, {"sting": "riser", "t": 18.5},
              {"bed": "cinematic_a", "t0": 20, "t1": 45}],
    "cues": [{"t": 8.4, "sfx": "hit"}, {"t": 9.0, "sfx": "kaboom"}],
    "captions": [{"t0": 1, "t1": 3, "text": "Every hero has a boss."}],
    "finish": {"grain": 0.04, "vignette": 0.9}},
    "plan": {
        "shots": [{"id": "walk", "intent": "party approaches the glowing boss door", "product_visible": True},
                  {"id": "boss", "intent": "the car is the boss; cursor clicks BUY", "product_visible": True},
                  {"id": "field", "intent": "red cars fly over a sunset flower field", "product_visible": True}],
        "custom_scenes": [{"name": "boss-battle", "layer": "2d", "describe": "Pixel boss battle with the car as boss",
                           "spec": SPEC, "params": {"boss_media": {"type": "asset", "default": None, "doc": "boss"},
                                                    "pick": {"type": "string", "default": "BUY", "doc": "menu"}},
                           "kits": ["fake"], "fallback": "kit:fake/walk"}]}}


def revised_film(**changes: Any) -> dict[str, Any]:
    out = copy.deepcopy(FILM)
    out["film"]["captions"] = [{"t0": 1, "t1": 3, "text": "Meet the boss."}]
    out["changes"] = ["shorter caption"]
    out["scene_notes"] = [{"name": "boss-battle", "notes": "make the boss twice as big"}]
    out.update(changes)
    return out


GOOD_CODE = """import { sr } from '../runtime/showreel.js';
sr.defineScene('custom:boss-battle', {
  layer: '2d',
  describe: 'Pixel boss battle',
  params: { boss_media: { type: 'asset', default: null, doc: 'boss' } },
  render(ctx, t, p) { const g = ctx.g; g.fillStyle = '#1a1c2c'; g.fillRect(0, 0, ctx.w, ctx.h); }
});
"""
BUGGY_CODE = GOOD_CODE.replace("render(ctx, t, p) {", "render(ctx, t, p) { /*THROW*/")
RANDOM_CODE = GOOD_CODE.replace("g.fillRect(0, 0, ctx.w, ctx.h);", "g.fillRect(Math.random(), 0, ctx.w, ctx.h);")


def fenced(code: str) -> str:
    return f"Here is the scene.\n```js\n{code}```\n"


def critique(score: float, issues: list[dict[str, Any]] | None = None, visible: bool = True,
             cells: int = 6, size: float = 0.45) -> dict[str, Any]:
    return {"scores": {k: score for k in ("product_clarity", "composition", "beauty_craft", "story_clarity",
                                          "legibility", "style_coherence", "transition_quality")},
            "frames": [{"cell": i + 1, "product_visible": visible, "product_size": size if visible else 0,
                        "note": ""} for i in range(cells)],
            "requirements": [{"text": "pixel", "met": True}],
            "per_shot_issues": issues or [], "strengths": ["bold colour"],
            "verdict": "pass" if score >= 8 and not issues else "revise"}


LOW_ISSUES = [{"shot": "boss", "target": "scene", "severity": 2, "issue": "boss too small", "fix": "scale it 2x"},
              {"shot": "walk", "target": "film", "severity": 2, "issue": "caption too long", "fix": "shorten it"}]


class FakeLlm:
    """Scripted model: replies are queued per purpose (exact purpose first, then the prefix before ':').

    The last reply of a queue repeats. Items may be dicts (JSON), strings, LlmReply or callables.
    """

    def __init__(self, script: dict[str, list[Any]]) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, purpose: str, instructions: str, text: str, images: Any = (), json_schema: Any = None,
                 schema_name: Any = None, temperature: float = 0.7, max_tokens: int = 0,
                 timeout: float = 0.0) -> LlmReply:
        self.calls.append({"purpose": purpose, "instructions": instructions, "text": text, "images": len(images),
                           "schema": json_schema is not None})
        q = self.script.get(purpose) or self.script.get(purpose.split(":")[0])
        if not q:
            return LlmReply(error=f"no scripted reply for {purpose}")
        item = q.pop(0) if len(q) > 1 else q[0]
        if callable(item):
            item = item(purpose=purpose, text=text, instructions=instructions)
        if isinstance(item, LlmReply):
            return item
        usage = {"input_tokens": 1000, "output_tokens": 200, "cost_usd": 0.01}
        if isinstance(item, (dict, list)):
            return LlmReply(text=json.dumps(item), parsed=copy.deepcopy(item), usage=usage, model="fake")
        return LlmReply(text=str(item), usage=usage, model="fake")

    def purposes(self) -> list[str]:
        return [c["purpose"] for c in self.calls]


class FakeRenderer:
    """Scripted runtime: scenes whose code contains /*THROW*/ raise at their shots; captures are solid PNGs."""

    def __init__(self, *, load_error: str = "", build_errors: list[str] | None = None) -> None:
        self.load_error = load_error
        self.build_errors = build_errors or []
        self.builds: list[dict[str, Any]] = []
        self.previews: list[dict[str, Any]] = []

    def validate_film(self, film: dict[str, Any]) -> list[str]:
        return []

    def lint_scene(self, code: str, scene_id: str) -> list[str]:
        return []

    def build(self, film: dict[str, Any], page_dir: Path, *, scenes: dict[str, str], assets: list[MediaAsset],
              library_dir: Path | None) -> list[str]:
        write_scenes(page_dir, scenes)
        (page_dir / "film.json").write_text(json.dumps(film), encoding="utf-8")
        self.builds.append({"film": copy.deepcopy(film), "scenes": dict(scenes)})
        return list(self.build_errors)

    def preview(self, page_dir: Path, *, probe_times: Any, capture_times: Any, size: tuple[int, int],
                film_size: tuple[int, int], shots: list[dict[str, Any]], determinism_times: Any = ()) -> Preview:
        self.previews.append({"probe": list(probe_times), "capture": list(capture_times), "size": size})
        if self.load_error:
            return Preview(ok=False, load_error=self.load_error)
        errors = []
        for s in shots:
            m = re.match(r"custom:(.+)$", s["scene"])
            if m and "/*THROW*/" in (page_dir / "scenes" / f"{m.group(1)}.js").read_text(encoding="utf-8"):
                errors.append(ShotError(s["id"], float(s["t0"]) + 0.5, "TypeError: boss is undefined"))
        return Preview(ok=True, errors=errors, images=[png((30, 30 + i % 200, 90)) for i, _ in
                                                       enumerate(capture_times)])
