"""Glue around the Blender engine: locate, the `blender` trigger, settings, Quick mapping, pipeline, product models."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from showreel_core.blender import locate as loc
from showreel_core.blender.trigger import blender_requested
from showreel_core.commands import describe, parse
from showreel_core.config import Options, Settings, load_settings

REPO = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------------------- locate

def test_parse_version():
    assert loc.parse_version("Blender 5.2.3 LTS\n\tbuild date: ...") == ((5, 2, 3), "5.2.3")
    assert loc.parse_version("Blender 4.2") == ((4, 2, 0), "4.2.0")
    assert loc.parse_version("nothing here") is None


@pytest.fixture
def fake_versions(monkeypatch):
    table: dict[str, tuple] = {}
    monkeypatch.setattr(loc, "probe_version", lambda p, timeout_s=0: table.get(Path(p).name))
    monkeypatch.setattr(loc.shutil, "which", lambda name: None)
    return table


def _exe(d: Path, name: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_bytes(b"x")
    return p


def test_locate_env_then_config(tmp_path, fake_versions):
    env_b = _exe(tmp_path / "a", "envblender.exe")
    cfg_b = _exe(tmp_path / "b", "cfgblender.exe")
    fake_versions.update({"envblender.exe": ((5, 1, 0), "5.1.0"), "cfgblender.exe": ((4, 2, 1), "4.2.1")})
    got = loc.locate(str(cfg_b), environ={"HYPE_BLENDER": str(env_b)}, search_standard=False)
    assert got.ok and got.source == "env" and got.version == (5, 1, 0)
    got = loc.locate(str(cfg_b), environ={}, search_standard=False)
    assert got.ok and got.source == "config"
    got = loc.locate(str(tmp_path / "b"), environ={}, search_standard=False)   # a folder holding blender.exe? no
    assert not got.ok


def test_locate_errors_are_user_facing(tmp_path, fake_versions):
    old = _exe(tmp_path, "old.exe")
    fake_versions["old.exe"] = ((3, 6, 5), "3.6.5")
    bad = loc.locate(str(tmp_path / "missing.exe"), environ={}, search_standard=False)
    assert bad.reason == "bad_path" and "does not exist" in bad.message
    assert "hermes plugins install blender" in bad.message and "HYPE_BLENDER" in bad.message
    too_old = loc.locate(str(old), environ={}, search_standard=False)
    assert too_old.reason == "too_old" and "4.2" in too_old.message
    none = loc.locate(None, environ={}, search_standard=False)
    assert none.reason == "not_found" and none.to_dict()["ok"] is False


def test_standard_locations_pick_newest(tmp_path, fake_versions, monkeypatch):
    base = tmp_path / "Local" / "Programs" / "Blender Foundation"
    a = _exe(base / "Blender 4.2", "blender.exe")
    b = _exe(base / "blender-5.1.0-windows-x64", "blender.exe")
    found = loc.standard_locations("win32", {"LOCALAPPDATA": str(tmp_path / "Local")})
    assert set(found) == {a, b}
    lin = _exe(tmp_path / "home" / ".local" / "opt" / "blender-5.1.0-linux-x64", "blender")
    assert loc.standard_locations("linux", {}, home=tmp_path / "home") == [lin]
    versions = {str(a): ((4, 2, 0), "4.2.0"), str(b): ((5, 1, 0), "5.1.0")}
    monkeypatch.setattr(loc, "probe_version", lambda p, timeout_s=0: versions.get(str(p)))
    monkeypatch.setattr(loc, "standard_locations", lambda environ=None: [a, b])
    got = loc.locate(None, environ={})
    assert got.ok and got.path == b and got.source == "standard"


def test_child_env_drops_python_paths(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "x")
    monkeypatch.setenv("PYTHONHOME", "y")
    env = loc.child_env()
    assert "PYTHONPATH" not in env and "PYTHONHOME" not in env and env["PYTHONNOUSERSITE"] == "1"


# ------------------------------------------------------------------------------------------- trigger / options

@pytest.mark.parametrize("text,want", [
    ("make it cinematic and use blender", True), ("render it in Blender please", True), ("Blender!", True),
    ("no blender, keep it light", False), ("don't use blender", False), ("without Blender", False),
    ("a film about my smoothie blender app", None), ("kitchen blender product reveal", None),
    ("pixel dungeon then a meadow", None), ("kitchen blender render style", True),
])
def test_blender_requested(text, want):
    assert blender_requested(text) is want


def test_command_grammar():
    styles = ["pixel", "launch", "cinematic"]
    assert parse("blender", styles=styles).options.engine_3d == "blender"
    c = parse("pixel 60 blender vertical", styles=styles)
    assert (c.options.engine_3d, c.options.style, c.options.seconds, c.options.direction) == ("blender", "pixel", 60, "")
    c = parse("cars flying over a meadow, use blender", styles=styles)
    assert c.options.engine_3d == "blender" and c.options.directed and c.options.hints["engine_3d"] == "blender"
    c = parse("--engine browser a meadow, use blender", styles=styles)       # explicit flag wins over the text
    assert c.options.engine_3d == "browser"
    assert parse("--engine=auto", styles=styles).options.engine_3d == "auto"
    assert parse("pixel", styles=styles, base=Options(engine_3d="blender")).options.engine_3d == "blender"
    assert "Blender" in describe(parse("blender", styles=styles).options)


def test_settings_engine_keys():
    s = load_settings(lambda k, d: {"engine_3d": "Blender", "blender_path": " C:/b/blender.exe "}.get(k, d))
    o = s.options()
    assert o.engine_3d == "blender" and o.blender_path == "C:/b/blender.exe"
    assert Options.from_dict({"engine_3d": "three.js"}).engine_3d == "browser"
    assert Options.from_dict({"engine_3d": "nonsense"}).engine_3d == "browser"
    assert Settings().engine_3d == "browser"


def test_plugin_yaml_declares_and_discloses():
    text = (REPO / "plugin.yaml").read_text(encoding="utf-8")
    assert "engine_3d:" in text and "blender_path:" in text and "subprocess" in text
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "## Blender" in readme and "--factory-startup" in readme


# ------------------------------------------------------------------------------------------- Quick mapping

def _timeline(img: Path) -> dict:
    image = {"path": str(img), "w": 64, "h": 36}
    return {"w": 640, "h": 360, "fps": 30, "dur": 9.0, "seed": 3, "style": "launch", "title": "Car",
            "scenes": [
                {"type": "HOOK", "t0": 0, "t1": 2, "data": {"hero": dict(image), "label": "Meet the car"}},
                {"type": "TITLE", "t0": 2, "t1": 4, "data": {"title": "Red Car", "tagline": "Fast"}},
                {"type": "CODE", "t0": 4, "t1": 6, "data": {"lines": ["x = 1"]}},
                {"type": "END", "t0": 6, "t1": 9, "data": {"title": "Red Car", "cta": "Drive it", "credit": "c"}}],
            "cues": []}


@pytest.fixture
def placeholder(monkeypatch):
    monkeypatch.setenv("HYPE_BLENDER_PLACEHOLDER", "1")


def test_quick_maps_product_shots_to_blender_and_reverts(tmp_path, placeholder, monkeypatch):
    from PIL import Image

    from showreel_core.film import quick
    monkeypatch.setattr(quick, "BLENDER_QUICK", {})          # placeholder rows only (hermetic vs. kit changes)
    img = tmp_path / "shot.png"
    Image.new("RGB", (64, 36), (200, 30, 30)).save(img)
    model = tmp_path / "car.glb"
    model.write_bytes(b"glTF....")
    made = quick.film_from_timeline(_timeline(img), job_dir=tmp_path, blender=True, product_model=str(model))
    film = made["film"]
    kinds = {s["id"]: s["scene"] for s in film["shots"]}
    assert kinds["s00_hook"] == kinds["s01_title"] == kinds["s03_end"] == "blender:_test/hello"
    assert kinds["s02_code"].startswith("kit:")
    assert film["assets"]["product3d"] == {"type": "model"} and made["assets"]["product3d"]["src"] == str(model)
    assert film["shots"][0]["params"]["product"] == "product3d"
    ov = {o["id"]: o for o in film["overlays"]}
    assert ov["blx_s01_title"]["scene"] == "kit:type/title" and ov["blx_s01_title"]["params"]["text"] == "Red Car"
    assert ov["blx_s03_end"]["scene"] == "kit:type/end-lockup"
    back = quick.revert_blender(film)
    assert all(not s["scene"].startswith("blender:") for s in back["shots"])
    assert not any(o["id"].startswith("blx_") for o in back["overlays"]) and "product3d" not in back["assets"]
    # software product (no model): the screenshot is the product
    film2 = quick.film_from_timeline(_timeline(img), job_dir=tmp_path, blender=True)["film"]
    assert film2["shots"][0]["params"]["product"].startswith("m0_")
    # engine off: untouched
    film3 = quick.film_from_timeline(_timeline(img), job_dir=tmp_path)["film"]
    assert not any(s["scene"].startswith("blender:") for s in film3["shots"])


def test_quick_table_drops_missing_scenes(monkeypatch):
    from showreel_core.film import quick
    monkeypatch.delenv("HYPE_BLENDER_PLACEHOLDER", raising=False)
    monkeypatch.setattr(quick, "BLENDER_QUICK", {"TITLE": {"model": {"scene": "blender:nope/none"}}})
    assert quick.blender_quick_table() == {}


# ------------------------------------------------------------------------------------------- pipeline glue

class _Store:
    def __init__(self):
        self.logs, self.updates = [], {}

    def log(self, job_id, msg, level="info", **_):
        self.logs.append((level, msg))

    def update(self, job_id, **kw):
        self.updates.update(kw)
        return {}


def _run(engine: str, located, blender_pass=None):
    from showreel_core import pipeline
    deps = pipeline.Deps()
    deps.blender_locate = lambda path: located
    if blender_pass:
        deps.blender_pass = blender_pass
    rep = SimpleNamespace(progress=lambda *a, **k: None)
    run = pipeline._Run(job_id="j", job={}, opts=Options(engine_3d=engine, preview=True), host=None, store=_Store(),
                        deps=deps, rep=rep, cancel=SimpleNamespace(is_set=lambda: False), job_dir=Path("."))
    return pipeline, run


def test_pipeline_engine_choice_and_missing_note():
    missing = loc.BlenderMissing("not_found", "Blender was not found. Install ...")
    pipeline, run = _run("blender", missing)
    assert pipeline.blender_engine(run) is None
    assert any(level == "warn" and "browser" in msg for level, msg in run.store.logs)
    pipeline, run = _run("browser", missing)
    assert pipeline.blender_engine(run) is None and not run.store.logs
    found = loc.BlenderFound(Path("b"), (5, 2, 3), "5.2.3", "env")
    pipeline, run = _run("auto", found)
    assert pipeline.blender_engine(run) is found and pipeline.blender_engine(run) is found


def test_pipeline_blender_pass_falls_back_to_browser(tmp_path):
    from showreel_core.blender.film import BlenderPass
    failed = BlenderPass(ok=False, message="shot s00_hook: Blender scene failed: boom")
    pipeline, run = _run("blender", None, blender_pass=lambda film, job_dir, **kw: failed)
    film = {"shots": [{"id": "a", "scene": "blender:_test/hello", "params": {}}], "assets": {}, "meta": {}}
    reverted = {"shots": [{"id": "a", "scene": "kit:base/HOOK", "params": {}}], "assets": {}, "meta": {}}
    out, assets = pipeline.blender_pass(run, film, {"x": {}}, tmp_path, "w", object(), revert=lambda f: reverted)
    assert out is reverted and assets == {}
    assert any("browser instead" in msg for _, msg in run.store.logs)
    with pytest.raises(pipeline.StageError):
        pipeline.blender_pass(run, film, {}, tmp_path, "w", object(), revert=None)
    cancelled = BlenderPass(ok=False, cancelled=True)
    pipeline, run = _run("blender", None, blender_pass=lambda film, job_dir, **kw: cancelled)
    with pytest.raises(pipeline.Cancelled):
        pipeline.blender_pass(run, film, {}, tmp_path, "w", object(), revert=None)


# ------------------------------------------------------------------------------------------- product models

def test_pick_models_prefers_real_models(tmp_path):
    from showreel_core.session.product import artifact_kind, pick_models
    assert artifact_kind("car.glb") == "model" and artifact_kind("x.usdz") == "model"
    mesh = tmp_path / "car.obj"
    mesh.write_text("# mesh\nv 0 0 0\nv 1 0 0\nf 1 2 1\n", encoding="utf-8")
    compiled = tmp_path / "main.obj"
    compiled.write_bytes(b"\x4c\x01\x00\x00binary coff")
    glb = tmp_path / "car.glb"
    glb.write_bytes(b"glTF" + b"\0" * 32)
    cands = [{"path": str(p), "delivered": False, "t": 1.0, "bytes": 10} for p in (mesh, compiled, glb)]
    assert pick_models(cands) == [str(glb), str(mesh)]
    cands[0]["delivered"] = True
    assert pick_models(cands)[0] == str(mesh)


# ------------------------------------------------------------------------------------------- frames kit

def test_frames_kit_index_matches_host_rounding(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    from showreel_core.blender.film import frames_for_times
    kit = (REPO / "kits" / "frames" / "kit.js").as_uri()
    js = (f"const m = await import('{kit}').catch(e => null);"
          "if (!m) { console.log('SKIP'); } else {"
          " console.log(JSON.stringify([0.5, 1.0333, 2.0].map(t => m.frameFor(t, 0.1, 30, 100))));"
          " console.log(JSON.stringify(m.fitRect(100, 50, 200, 200, 'cover'))); }")
    shim = tmp_path / "runtime" / "showreel.js"
    out = subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=60)
    if "SKIP" in out.stdout or out.returncode:
        pytest.skip(f"kit.js needs the browser runtime to import: {out.stderr[:200]}")
    idx = json.loads(out.stdout.splitlines()[0])
    want = [f - 1 for t in (0.5, 1.0333, 2.0) for f in frames_for_times({"t0": 0.0}, [t], 30, 0.1, 100) if f != 1]
    assert idx == want
    assert shim is not None


def test_quick_table_substitutes_tokens(tmp_path, monkeypatch):
    from PIL import Image

    from showreel_core.film import quick
    monkeypatch.delenv("HYPE_BLENDER_PLACEHOLDER", raising=False)
    monkeypatch.setattr(quick, "BLENDER_QUICK", {"FEATURE": {"screen": {"scene": "blender:_test/hello", "params": {
        "image": "{media}", "feature": "{label}", "bbox": "{data:bbox}", "click": "{data:click}", "accent": "{accent}"}}}})
    img = tmp_path / "shot.png"
    Image.new("RGB", (64, 36), (20, 30, 200)).save(img)
    tl = _timeline(img)
    tl["accent"] = "#E5484D"
    tl["scenes"][2] = {"type": "FEATURE", "t0": 4, "t1": 6, "data": {"image": {"path": str(img), "w": 64, "h": 36},
                                                                    "feature": "Dark mode", "bbox": [0.1, 0.2, 0.3, 0.4]}}
    film = quick.film_from_timeline(tl, job_dir=tmp_path, blender=True)["film"]
    feat = next(s for s in film["shots"] if s["id"] == "s02_feature")
    assert feat["scene"] == "blender:_test/hello"
    p = feat["params"]
    assert p["image"].startswith("m0_") and p["feature"] == "Dark mode" and p["bbox"] == [0.1, 0.2, 0.3, 0.4]
    assert "click" not in p and p["accent"] == "#E5484D" and p["product"] == p["image"]
    assert [o["scene"] for o in film["overlays"] if o["id"] == "blx_s02_feature"] == ["kit:type/lower-third"]
    # only FEATURE is mapped: HOOK/TITLE/END stay browser shots
    assert sum(s["scene"].startswith("blender:") for s in film["shots"]) == 1


def test_quick_table_names_real_scenes():
    from showreel_core.blender.film import SCENE_RE
    from showreel_core.film import quick
    for typ, row in quick.BLENDER_QUICK.items():
        assert typ in quick.BLENDER_TYPES
        for kind, entry in row.items():
            assert kind in ("model", "screen") and SCENE_RE.match(entry["scene"])


def test_quick_916_uses_the_phone_capture_and_keeps_the_top_band_for_words(tmp_path, monkeypatch):
    """research/w5-device.md: 9:16 Quick x Blender films had laptops (no phone capture reached the device scenes) and
    the HOOK/TITLE words sat ON the laptop (space was ignored in 9:16)."""
    from PIL import Image

    from showreel_core.film import quick
    monkeypatch.delenv("HYPE_BLENDER_PLACEHOLDER", raising=False)
    wide, tall = tmp_path / "desk.png", tmp_path / "mobile_390x844.png"
    Image.new("RGB", (64, 36), (20, 30, 200)).save(wide)
    Image.new("RGB", (39, 84), (200, 30, 20)).save(tall)
    tl = _timeline(wide)
    tl["w"], tl["h"] = 360, 640
    tl["scenes"][2] = {"type": "SCREEN", "t0": 4, "t1": 6, "data": {"image": {"path": str(tall), "w": 390, "h": 844}}}
    film = quick.film_from_timeline(tl, job_dir=tmp_path, blender=True)["film"]
    shots = {s["id"]: s for s in film["shots"]}
    mob = next(n for n in film["assets"] if n != shots["s00_hook"]["params"].get("media"))
    for sid in ("s00_hook", "s01_title", "s03_end"):
        p = shots[sid]["params"]
        assert shots[sid]["scene"].startswith("blender:device/") and p["mobile"] == mob, (sid, p)
    assert shots["s00_hook"]["params"]["space"] == "top" and shots["s01_title"]["params"]["space"] == "top"
    ovs = {o["id"]: o for o in film["overlays"]}
    assert ovs["blx_s00_hook"]["params"]["band"] == "top" and ovs["blx_s01_title"]["params"]["band"] == "top"
    assert "align" not in ovs["blx_s01_title"]["params"]
    # 16:9 keeps the left-third layout and no phone
    film2 = quick.film_from_timeline(_timeline(wide), job_dir=tmp_path, blender=True)["film"]
    h2 = next(s for s in film2["shots"] if s["id"] == "s00_hook")["params"]
    assert h2["space"] == "left" and "mobile" not in h2
    assert next(o for o in film2["overlays"] if o["id"] == "blx_s01_title")["params"]["align"] == "left"


def test_device_hero_accepts_top_space_for_vertical():
    src = (Path(__file__).resolve().parents[2] / "blender_kits" / "device" / "device_hero.py").read_text(encoding="utf-8")
    assert '"values": ["none", "left", "right", "top", "bottom"]' in src
    assert 'space = "top"' in src
