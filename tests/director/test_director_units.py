"""Unit tests: catalog parsing, quality gates (treatment/film checks, lint), sheets, prompts, model adapters."""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from director_fakes import FILM, GOOD_CODE, RANDOM_CODE, SPEC, TREATMENT, FakeLlm, critique, png

from showreel_core.director import checks, prompts
from showreel_core.director.backend import attribute
from showreel_core.director.catalog import build_catalog, top_level_keys
from showreel_core.director.library import as_library_code, save_scene
from showreel_core.director.llm import (
    BudgetExceeded,
    CallLedger,
    Cancelled,
    Image,
    hermes_llm,
    is_cancelled,
    parse_stream_json,
)
from showreel_core.director.sheet import contact_sheets, plan_keyframes

# ------------------------------------------------------------------------------------ catalog


def test_catalog_reads_kits_both_registration_styles(env: dict[str, Any]) -> None:
    cat = env["catalog"]
    scenes = cat.scenes()
    assert {"kit:fake/walk", "kit:fake/field", "kit:fake/title"} <= set(scenes)
    assert scenes["kit:fake/walk"].params == ["party", "media"]
    assert scenes["kit:fake/field"].params == ["flyers", "time"]            # params: FIELD (const reference)
    assert scenes["kit:fake/field"].describe.startswith("Anime flower field")
    assert "kit:fake/petal-bloom" in cat.transitions() and "crossfade" in cat.transitions()
    assert [b.id for b in cat.beds] == ["cinematic_a", "pixel_a"]
    assert cat.stings() == ["hit", "riser"]
    text = cat.overview()
    assert "`kit:fake/walk`" in text and "`car`: video 1280x720, 6.0s" in text and "pixel_a" in text
    assert "Pixel and nature scenes for tests" in cat.full()


def test_catalog_library_entries(env: dict[str, Any]) -> None:
    sid = save_scene(env["library"], "Boss Battle", GOOD_CODE, {"describe": "boss fight", "layer": "2d",
                                                                 "params": {"boss_media": {"type": "asset"}}}, png())
    assert sid == "lib:boss-battle"
    assert save_scene(env["library"], "boss-battle", GOOD_CODE, {}) is None              # identical: skipped
    other = GOOD_CODE.replace("#1a1c2c", "#000000")
    assert save_scene(env["library"], "boss-battle", other, {}) == "lib:boss-battle-2"     # never overwrites
    cat = build_catalog(kits_dir=env["kits"], audio_dir=env["audio"], library_dir=env["library"])
    lib = {e.id: e for e in cat.library}
    assert lib["lib:boss-battle"].describe == "boss fight" and lib["lib:boss-battle"].thumbnail.endswith("thumb.jpg")
    assert "lib:boss-battle" in cat.scenes()
    assert "sr.defineScene('lib:x'" in as_library_code(GOOD_CODE, "x")


def test_top_level_keys_ignores_nesting_and_strings() -> None:
    src = "{ a: { type: 'list', default: {x: 1} }, 'b-c': 2, d: \"e: {\", f: [1, {g: 2}] }"
    assert top_level_keys(src) == ["a", "b-c", "d", "f"]


# ------------------------------------------------------------------------------------ treatment gate


def test_treatment_rescales_and_drops_unknowns(env: dict[str, Any]) -> None:
    chk = checks.check_treatment(TREATMENT, env["brief"], env["catalog"])
    assert chk.ok, chk.errors
    assert sum(a["duration"] for a in chk.value["acts"]) == pytest.approx(45.0, abs=0.05)
    assert [m["bed"] for m in chk.value["music_plan"]] == ["pixel_a"]


@pytest.mark.parametrize("mutate,needle", [
    (lambda t: t["hook"].update(t=3.5), "within 2 s"),
    (lambda t: t.update(requirements=[]), "requirements"),
    (lambda t: t.update(asset_plan=[]), "product media"),
    (lambda t: t["acts"][0].update(duration=60), "add up to"),
])
def test_treatment_errors(env: dict[str, Any], mutate: Any, needle: str) -> None:
    t = copy.deepcopy(TREATMENT)
    mutate(t)
    chk = checks.check_treatment(t, env["brief"], env["catalog"])
    assert any(needle in e for e in chk.errors), chk.errors


# ------------------------------------------------------------------------------------ film gate


def _check(env: dict[str, Any], obj: dict[str, Any]) -> checks.Checked:
    return checks.check_film(obj, env["brief"], env["catalog"], max_custom=3)


def test_film_check_passes_and_matches_runtime_schema(env: dict[str, Any]) -> None:
    chk = _check(env, FILM)
    assert chk.ok, chk.errors
    film, plan = chk.value
    from showreel_core.film.schema import errors_of, validate_film
    errs = errors_of(validate_film(film))
    assert not errs, [str(e) for e in errs]
    assert plan["custom_scenes"][0]["kits"] == ["fake"]


def test_film_check_fixes_small_gaps_and_flags_big_ones(env: dict[str, Any]) -> None:
    obj = copy.deepcopy(FILM)
    obj["film"]["shots"][1]["t0"] = 6.3
    obj["film"]["shots"][2]["t1"] = 44.5
    chk = _check(env, obj)
    shots = chk.value[0]["shots"]
    assert chk.ok and shots[0]["t1"] == shots[1]["t0"] and abs(shots[0]["t1"] - 6.3) <= 0.2
    assert shots[2]["t1"] == 45.0
    obj["film"]["shots"][1]["t0"] = 9.0
    assert any("back to back" in e for e in _check(env, obj).errors)


def test_film_check_product_share_and_hook(env: dict[str, Any]) -> None:
    obj = copy.deepcopy(FILM)
    obj["film"]["shots"][2]["params"] = {"time": "sunset"}
    obj["film"]["shots"][0]["params"].pop("media")
    chk = _check(env, obj)
    assert any("only 31%" in e for e in chk.errors), chk.errors
    assert any("first appears at 6 s" in w for w in chk.warnings)
    obj["film"]["shots"][1]["params"].pop("boss_media")
    obj["film"]["overlays"][0]["params"]["media"] = "car"          # product only on the end card at 41 s
    assert any("first appears at 41 s" in e for e in _check(env, obj).errors)


def test_film_check_custom_scene_rules(env: dict[str, Any]) -> None:
    obj = copy.deepcopy(FILM)
    obj["plan"]["custom_scenes"][0]["spec"] = "a boss"
    obj["film"]["shots"][1]["params"]["boss_media"] = "truck"
    errs = _check(env, obj).errors
    assert any("too vague" in e for e in errs) and any("unknown assets ['truck']" in e for e in errs)
    obj = copy.deepcopy(FILM)
    obj["plan"]["custom_scenes"] = []
    assert any("no entry in plan.custom_scenes" in e for e in _check(env, obj).errors)
    obj = copy.deepcopy(FILM)
    assert any("at most 0" in e for e in checks.check_film(obj, env["brief"], env["catalog"], max_custom=0).errors)


def test_film_check_transition_window_and_captions(env: dict[str, Any]) -> None:
    obj = copy.deepcopy(FILM)
    obj["film"]["transitions"][0].update(t=25.0, type="star-wipe")
    obj["film"]["captions"] = [{"t0": 1, "t1": 4, "text": "One"}, {"t0": 3, "t1": 5, "text": "Two"},
                               {"t0": 6, "t1": 8, "text": " ".join(["word"] * 16)}]
    chk = _check(env, obj)
    tr = chk.value[0]["transitions"][0]
    assert tr["type"] == "crossfade" and tr["t"] <= 20.0 <= tr["t"] + tr["dur"]
    assert any("16 words" in e for e in chk.errors)
    caps = chk.value[0]["captions"]
    assert caps[0]["t1"] == 3.0


def test_cuts_snap_to_the_beat(env: dict[str, Any]) -> None:
    obj = copy.deepcopy(FILM)
    obj["film"]["shots"][0]["t1"] = obj["film"]["shots"][1]["t0"] = 6.13      # beat at 150 BPM = 0.4 s -> 6.0
    chk = _check(env, obj)
    assert chk.ok and chk.value[0]["shots"][0]["t1"] == 6.0
    assert any("snapped" in w for w in chk.warnings)


# ------------------------------------------------------------------------------------ scene code


def test_extract_and_normalise_scene_code() -> None:
    reply = "Sure!\n```javascript\n" + GOOD_CODE.replace("custom:boss-battle", "custom:boss") + "```\nEnjoy."
    code = checks.normalize_scene_code(checks.extract_js(reply), "custom:boss-battle")
    assert code.startswith(checks.RUNTIME_IMPORT) and code.count("import {") == 1
    assert "defineScene('custom:boss-battle'" in code
    assert checks.lint_scene(code, "custom:boss-battle") == ([], [])
    truncated = "```js\n" + GOOD_CODE[:-10]
    errs, _ = checks.lint_scene(checks.extract_js(truncated), "custom:boss-battle")
    assert any("truncated" in e or "unbalanced" in e for e in errs)


@pytest.mark.parametrize("snippet,needle", [
    ("const r = Math.random();", "Math.random"),
    ("const d = Date.now();", "Date"),
    ("setTimeout(() => 0, 5);", "timers"),
    ("fetch('x');", "network"),
    ("document.body.appendChild(x);", "document"),
    ("const u = 'https://example.com/a.png';", "external URLs"),
    ("const f = new Function('return 1');", "eval"),
])
def test_lint_rejects_forbidden_apis(snippet: str, needle: str) -> None:
    code = GOOD_CODE.replace("render(ctx, t, p) {", "render(ctx, t, p) { " + snippet)
    errs, _ = checks.lint_scene(code, "custom:boss-battle")
    assert any(needle in e for e in errs), errs


def test_lint_ignores_comments_and_strings() -> None:
    code = GOOD_CODE.replace("render(ctx, t, p) {", "render(ctx, t, p) { // no Math.random or Date here\n"
                             " const label = 'Date night'; const s = `It's (`;")
    assert checks.lint_scene(code, "custom:boss-battle")[0] == []
    errs, _ = checks.lint_scene(RANDOM_CODE, "custom:boss-battle")
    assert errs and "Math.random" in errs[0]
    errs, _ = checks.lint_scene(GOOD_CODE.replace("custom:boss-battle", "custom:other"), "custom:boss-battle")
    assert any("must be `custom:boss-battle`" in e for e in errs)


def test_nearest_kit_scene_and_fallback_params(env: dict[str, Any]) -> None:
    spec = {"name": "meadow-flyby", "layer": "2d", "describe": "cars fly over a flower field at sunset", "spec": SPEC}
    target = checks.nearest_kit_scene(spec, env["catalog"])
    assert target is not None and target.id == "kit:fake/field"
    params = checks.fallback_params(spec, {"car_media": "car", "time": "dusk"}, target, {"car"})
    assert params == {"time": "dusk"}                 # kit has no media-like slot: only declared params kept
    walk = env["catalog"].scenes()["kit:fake/walk"]
    assert checks.fallback_params(spec, {"boss_media": "car"}, walk, {"car"}) == {"media": "car"}


def test_runtime_error_attribution() -> None:
    shots = [{"id": "walk", "scene": "kit:fake/walk"}, {"id": "boss", "scene": "custom:boss-battle"}]
    assert attribute("shot boss: render t=3.200: TypeError: x is undefined", shots) == ("boss", 3.2)
    assert attribute("module scenes/boss-battle.js failed to load: SyntaxError", shots)[0] == "boss"
    assert attribute("something else", shots) == ("", None)


# ------------------------------------------------------------------------------------ sheets


def test_keyframe_plan() -> None:
    film = copy.deepcopy(FILM["film"])
    frames = plan_keyframes(film, 3)
    assert len(frames) == 3 * 3 + 1                      # 3 per shot + transition midpoint (1.2 s covers the hook)
    assert [f.cell for f in frames] == list(range(1, len(frames) + 1))
    assert any(f.transition == "boss->field kit:fake/petal-bloom" for f in frames)
    assert all(frames[i].t <= frames[i + 1].t for i in range(len(frames) - 1))
    assert len(plan_keyframes(film, 5, max_frames=8)) <= 8


def test_contact_sheet(tmp_path: Path) -> None:
    frames = plan_keyframes(copy.deepcopy(FILM["film"]), 5)
    paths = contact_sheets([png() for _ in frames] , frames, tmp_path, max_cells=12)
    assert len(paths) == 2 and all(p.stat().st_size > 1000 for p in paths)
    from PIL import Image
    with Image.open(paths[0]) as im:
        assert im.width > 1900


# ------------------------------------------------------------------------------------ prompts


def test_prompts_carry_direction_doctrine_and_catalog(env: dict[str, Any]) -> None:
    instr, text = prompts.treatment_prompt(env["brief"], env["catalog"])
    assert env["brief"].direction in text and "DIRECTOR'S DOCTRINE" in instr and "`kit:fake/walk`" in text
    instr, text = prompts.film_prompt(env["brief"], env["catalog"], TREATMENT, max_custom=3)
    assert "at most 3 custom scene(s)" in instr and "Beat grid" in text and "sr.defineScene" in text
    spec = FILM["plan"]["custom_scenes"][0]
    instr, text = prompts.scene_prompt(env["brief"], env["catalog"], spec, FILM["film"]["shots"][1:2], {})
    assert "custom:boss-battle" in instr and "PURE-FUNCTION RULE" in text and "Pixel art" in instr
    frames = [f.to_dict() for f in plan_keyframes(copy.deepcopy(FILM["film"]), 1)]
    instr, text = prompts.critic_prompt(env["brief"], TREATMENT, FILM["film"], FILM["plan"], frames, ["fact"])
    assert "cell 1: shot `walk`" in text and "product_clarity" in instr and "- fact" in text


def _walk(schema: Any) -> list[str]:
    keys = []
    if isinstance(schema, dict):
        keys += list(schema)
        for v in schema.values():
            keys += _walk(v)
    elif isinstance(schema, list):
        for v in schema:
            keys += _walk(v)
    return keys


@pytest.mark.parametrize("schema", [prompts.TREATMENT_SCHEMA, prompts.FILM_SCHEMA, prompts.CRITIC_SCHEMA,
                                    prompts.REVISE_FILM_SCHEMA])
def test_transport_schemas_are_portable(schema: dict[str, Any]) -> None:
    banned = {"pattern", "minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems", "format"}
    assert not banned & set(_walk(schema))
    json.dumps(schema)


# ------------------------------------------------------------------------------------ model adapters


class _Res:
    def __init__(self, text: str = "{}", parsed: Any = None) -> None:
        self.text, self.parsed = text, parsed
        self.content_type = "json" if parsed is not None else "text"
        self.provider, self.model = "p", "m"
        self.usage = {"input_tokens": 7, "output_tokens": 3}


class PluginLlmTrustError(PermissionError):
    pass


def test_hermes_llm_adapter_task_fallback_and_images() -> None:
    seen: list[dict[str, Any]] = []

    class Ctx:
        def complete_structured(self, **kw: Any) -> _Res:
            seen.append(kw)
            if kw["task"] == "showreel":
                raise PluginLlmTrustError("slot not registered")
            return _Res('{"a": 1}', {"a": 1})

    call = hermes_llm(Ctx())
    rep = call(purpose="critic:r1", instructions="i", text="t", images=[Image(b"\x89PNG", "image/png")],
               json_schema={"type": "object"}, schema_name="x")
    assert rep.parsed == {"a": 1} and rep.usage == {"input_tokens": 7, "output_tokens": 3}
    assert [k["task"] for k in seen] == ["showreel", None]
    assert seen[1]["input"][1] == {"type": "image", "data": b"\x89PNG", "mime_type": "image/png"}
    assert seen[1]["purpose"] == "showreel.critic:r1"


def test_hermes_llm_retries_in_json_mode_after_host_schema_rejection() -> None:
    seen: list[dict[str, Any]] = []

    class Ctx:
        def complete_structured(self, **kw: Any) -> _Res:
            seen.append(kw)
            if "json_schema" in kw:
                raise ValueError("Plugin LLM structured output did not match schema: 'x' is required")
            return _Res('```json\n{"b": 2}\n```')

    rep = hermes_llm(Ctx(), task=None)(purpose="film", instructions="i", text="t", json_schema={"type": "object"})
    assert rep.parsed == {"b": 2} and seen[1].get("json_mode") is True


def test_hermes_llm_errors_become_replies() -> None:
    class Ctx:
        def complete_structured(self, **kw: Any) -> _Res:
            raise TimeoutError("slow")
    rep = hermes_llm(Ctx())(purpose="x", instructions="i", text="t")
    assert rep.error.startswith("TimeoutError")


def test_parse_stream_json() -> None:
    out = "\n".join([json.dumps({"type": "system"}), json.dumps({"type": "text", "text": "ab"}),
                     json.dumps({"type": "result", "text": "abc", "tokens": {"input": 9, "output": 2}}),
                     "session_id: x"])
    got = parse_stream_json(out)
    assert got["text"] == "abc" and got["input"] == 9 and got["output"] == 2


def test_ledger_persists_counts_and_enforces_budget(tmp_path: Path) -> None:
    llm = FakeLlm({"critic": [critique(7.0)]})
    led = CallLedger(llm, tmp_path / "calls", max_calls=2)
    led(purpose="critic:r1", instructions="i", text="t", json_schema={"type": "object"})
    led(purpose="critic:r2", instructions="i", text="t")
    with pytest.raises(BudgetExceeded):
        led(purpose="critic:r3", instructions="i", text="t")
    tot = led.totals()
    assert tot["calls"] == 2 and tot["input_tokens"] == 2000 and tot["cost_usd"] == 0.02
    assert tot["by_purpose"] == {"critic": 2}
    assert sorted(p.name for p in (tmp_path / "calls").iterdir())[:3] == [
        "01-critic-r1.meta.json", "01-critic-r1.prompt.md", "01-critic-r1.reply.txt"]


def test_ledger_and_cancel_tokens(tmp_path: Path) -> None:
    ev = threading.Event()
    led = CallLedger(FakeLlm({"x": ["ok"]}), None, max_calls=5, cancel=ev)
    led(purpose="x", instructions="i", text="t")
    ev.set()
    with pytest.raises(Cancelled):
        led(purpose="x", instructions="i", text="t")

    class Token:
        def is_set(self) -> bool:
            return True
    assert is_cancelled(Token()) and is_cancelled(lambda: True) and not is_cancelled(None)


def test_catalog_reads_kit_md_scene_tables(tmp_path: Path) -> None:
    kit = tmp_path / "kits" / "demo"
    kit.mkdir(parents=True)
    (kit / "kit.js").write_text("export const x = { id: 'kit:demo/walk', def: { describe: 'walk' } };\n",
                                encoding="utf-8")
    (kit / "KIT.md").write_text(
        "# Demo kit\nA demo.\n\n## Scenes\n| id | what it shows | params (default) |\n|---|---|---|\n"
        r"| `kit:demo/HOOK` | Opening hook \| bold. | `title` "" — headline · `accent` — colour |" "\n"
        "| `kit:demo/walk` | duplicate of the JS one | `x` |\n\n## Types\n"
        "| `kit:demo/CODE` | `{path, lines}` — code card |\n\n## Transitions\n"
        "| `kit:demo/swirl` | battle swirl | `dur` |\n| `kit:other/NOPE` | not ours | |\n", encoding="utf-8")
    cat = build_catalog(kits_dir=tmp_path / "kits", library_dir=tmp_path / "lib", audio_dir=tmp_path / "audio")
    scenes = cat.scenes()
    assert {"kit:demo/HOOK", "kit:demo/walk", "kit:demo/CODE"} <= set(scenes) and "kit:other/NOPE" not in scenes
    assert scenes["kit:demo/HOOK"].params == ["title", "accent"] and "bold" in scenes["kit:demo/HOOK"].describe
    assert scenes["kit:demo/walk"].describe == "walk"                       # JS registration wins
    assert "{path, lines}" in scenes["kit:demo/CODE"].params_src
    assert cat.kits[0].transitions == ["kit:demo/swirl"]
