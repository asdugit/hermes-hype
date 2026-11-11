"""dashboard/plugin_api.py routes the Desktop pane uses (temp plugin data dir, no Hermes, no renders)."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from .conftest import P, jpeg, write_json

# ------------------------------------------------------------------------------------- basics


def test_health(api: dict[str, Any]) -> None:
    assert api["client"].get(f"{P}/health").json() == {"ok": True, "api": 2}


def test_styles_follow_the_roster_and_report_previews(api: dict[str, Any]) -> None:
    c, previews = api["client"], api["previews"]
    jpeg(previews / "pixel.jpg", (64, 36))                       # small: rides along inline
    (previews / "cinematic.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    styles = c.get(f"{P}/styles").json()["styles"]
    ids = [s["id"] for s in styles]
    assert ids[:2] == ["launch", "cinematic"] and ids.index("pixel") < ids.index("terminal")
    by = {s["id"]: s for s in styles}
    assert by["pixel"]["has_preview"] and by["pixel"]["preview_kind"] == "image"
    assert by["pixel"]["preview_url"].startswith("data:image/jpeg;base64,")
    assert by["cinematic"]["preview_kind"] == "video" and by["cinematic"]["preview_url"] == ""
    assert not by["launch"]["has_preview"] and "preview" not in by["launch"]
    video = c.get(f"{P}/styles/cinematic/preview").json()
    assert video["kind"] == "video" and video["url"].startswith("data:video/mp4;base64,")
    assert c.get(f"{P}/styles/launch/preview").status_code == 404
    assert c.get(f"{P}/styles/..%2Fx/preview").status_code == 404


def test_active_jobs_lists_running_and_just_finished(api: dict[str, Any]) -> None:
    store, c = api["store"], api["client"]
    running = store.create("s1", {"style": "pixel"})
    store.update(running["id"], stage="render", pct=0.42, eta_s=80, title="Tiny App")
    fresh = store.create("s2", {})
    store.update(fresh["id"], stage="done", finished=time.time() - 5, outputs={"16:9": "x.mp4"})
    old = store.create("s3", {})
    store.update(old["id"], stage="done", finished=time.time() - 3600)
    jobs = c.get(f"{P}/jobs/active").json()["jobs"]
    by = {j["id"]: j for j in jobs}
    assert set(by) == {running["id"], fresh["id"]}
    assert by[running["id"]]["pct"] == 0.42 and by[running["id"]]["style"] == "pixel"
    assert by[fresh["id"]]["outputs"] == ["16:9"] and "log" not in by[fresh["id"]]
    # the cached list notices updates (mtime/size keyed)
    store.update(running["id"], stage="mix", pct=0.9)
    again = {j["id"]: j for j in c.get(f"{P}/jobs/active").json()["jobs"]}
    assert again[running["id"]]["stage"] == "mix"


def test_active_jobs_say_whether_the_film_is_narrated(api: dict[str, Any]) -> None:
    """The status chip names the stage ('Mixing the music' vs '... and voice') from the row's ``voice`` flag."""
    store, c = api["store"], api["client"]
    quiet = store.create("s1", {"style": "pixel", "voice": False})
    loud = store.create("s2", {"style": "pixel", "voice": True})
    for j in (quiet, loud):
        store.update(j["id"], stage="mix", pct=0.9)
    by = {j["id"]: j for j in c.get(f"{P}/jobs/active").json()["jobs"]}
    assert by[quiet["id"]]["voice"] is False and by[loud["id"]]["voice"] is True


def test_a_long_silent_job_of_this_process_is_not_marked_stale(api: dict[str, Any]) -> None:
    """The dashboard's pipeline copy does not know jobs the plugin's copy runs in the same process."""
    store, c = api["store"], api["client"]
    other = store.create("s-busy", {})
    store.update(other["id"], stage="storyboard", pid=os.getpid())
    job_file = store.job_dir(other["id"]) / "job.json"
    past = time.time() - 300                                    # 5 minutes silent (a long Director call)
    data = store.load(other["id"])
    data["updated"] = past
    job_file.write_text(__import__("json").dumps(data), encoding="utf-8")
    assert c.post(f"{P}/jobs", json={"session_id": "s-new"}).status_code == 200
    assert store.load(other["id"])["stage"] == "storyboard"


# ------------------------------------------------------------------------------- storyboard / revise


def test_get_storyboard_prefers_the_pane_edit(api: dict[str, Any]) -> None:
    store, c = api["store"], api["client"]
    job = store.create("s1", {})
    sb = {"title": "T", "tagline": "Tag", "scenes": [{"type": "TITLE", "refs": [], "vo": "x"}]}
    store.update(job["id"], stage="done", storyboard=sb, storyboard_source="llm")
    r = c.get(f"{P}/jobs/{job['id']}/storyboard").json()
    assert r["storyboard"] == sb and r["edited"] is False and r["source"] == "llm"
    edit = dict(sb, title="T2")
    assert c.put(f"{P}/jobs/{job['id']}/storyboard", json={"storyboard": edit}).status_code == 200
    r = c.get(f"{P}/jobs/{job['id']}/storyboard").json()
    assert r["storyboard"]["title"] == "T2" and r["edited"] is True
    assert c.get(f"{P}/jobs/20200101-000000-dead/storyboard").status_code == 404


def test_revise_needs_notes_and_a_finished_film(api: dict[str, Any]) -> None:
    store, c = api["store"], api["client"]
    job = store.create("s1", {"style": "terminal", "seconds": 30, "aspects": ["9:16"]})
    assert c.post(f"{P}/jobs/{job['id']}/revise", json={"notes": ""}).status_code == 400
    assert c.post(f"{P}/jobs/{job['id']}/revise", json={"notes": "x" * 2001}).status_code == 400
    store.update(job["id"], stage="render")
    assert c.post(f"{P}/jobs/{job['id']}/revise", json={"notes": "faster"}).status_code == 409
    store.update(job["id"], stage="done")
    r = c.post(f"{P}/jobs/{job['id']}/revise", json={"notes": "  open on the dashboard  "})
    assert r.status_code == 200, r.text
    child = store.load(r.json()["id"])
    assert child["parent"] == job["id"] and child["kind"] == "quick"
    assert child["options"]["notes"] == "open on the dashboard"
    assert child["options"]["style"] == "terminal" and child["options"]["aspects"] == ["9:16"]
    assert api["started"][-1] == child["id"]
    assert c.post(f"{P}/jobs/{job['id']}/revise", json={"notes": "again"}).status_code == 409   # one at a time


def test_revise_of_a_directed_film_stays_directed(api: dict[str, Any]) -> None:
    store, c = api["store"], api["client"]
    job = store.create("s1", {"direction": "pixel, then anime", "effort": "quick"}, kind="directed")
    store.update(job["id"], stage="done")
    r = c.post(f"{P}/jobs/{job['id']}/revise",
               json={"notes": "bigger car", "options": {"direction": "hijack", "aspects": ["9:16"]}})
    child = store.load(r.json()["id"])
    assert child["kind"] == "directed" and child["options"]["direction"] == "pixel, then anime"
    assert child["options"]["notes"] == "bigger car" and child["options"]["aspects"] == ["9:16"]


@pytest.mark.parametrize(("notes", "start", "aspects"), [
    ("make a 9:16 version", ["16:9"], ["9:16"]), ("a vertical cut for reels", ["16:9"], ["9:16"]),
    ("now 16x9 please", ["9:16"], ["16:9"]), ("bigger car in act two", ["16:9"], ["16:9"]),
    ("both 16:9 and 9:16", ["16:9"], ["16:9"]),
])
def test_revise_notes_can_ask_for_the_other_aspect(api: dict[str, Any], notes: str, start: list[str],
                                                   aspects: list[str]) -> None:
    """A Directed film renders one aspect per run; the pane says 'use Revise: make a 9:16 version', so the notes
    must change the aspect (else the revision re-made the 16:9 film)."""
    store, c = api["store"], api["client"]
    job = store.create("s-asp", {"direction": "a noir trailer", "aspects": start}, kind="directed")
    store.update(job["id"], stage="done")
    r = c.post(f"{P}/jobs/{job['id']}/revise", json={"notes": notes})
    assert r.status_code == 200, r.text
    assert store.load(r.json()["id"])["options"]["aspects"] == aspects


def test_rerender_of_a_directed_film_explains_itself(api: dict[str, Any]) -> None:
    store, c = api["store"], api["client"]
    job = store.create("s1", {"direction": "make it epic"}, kind="directed")
    store.update(job["id"], stage="done")
    r = c.post(f"{P}/jobs/{job['id']}/rerender", json={"aspects": ["9:16"]})
    assert r.status_code == 409 and r.json()["directed"] is True and "Revise" in r.json()["error"]


# --------------------------------------------------------------------------------- the Director


def _director_job(api: dict[str, Any]) -> tuple[str, Path]:
    store = api["store"]
    job = store.create("s1", {"direction": "pixel but transition mid way, sell it"}, kind="directed")
    store.update(job["id"], stage="storyboard")
    jd = store.job_dir(job["id"])
    dd = jd / "director"
    sheet = jpeg(dd / "v1" / "contact-1.jpg")
    jpeg(dd / "v1" / "keyframes" / "01-hook.png", (320, 180))
    (dd / "v1" / "scenes").mkdir(parents=True)
    (dd / "v1" / "scenes" / "boss-fight.js").write_text("sr.defineScene('custom:boss-fight', {\n})\n",
                                                         encoding="utf-8")
    write_json(dd / "treatment.json", {"title": "Red Car", "logline": "A car levels up.",
                                       "acts": [{"name": "Act 1", "style": "pixel", "duration": 20, "world": "dungeon"}],
                                       "requirements": [{"text": "pixel", "how": "..."}]})
    write_json(dd / "v1" / "critique.json", {"scores": {"product_clarity": 6, "composition": 5, "beauty_craft": 5,
                                                         "story_clarity": 6, "legibility": 4, "style_coherence": 5,
                                                         "transition_quality": 5},
                                              "verdict": "revise", "per_shot_issues": [{"shot": "hook"}]})
    write_json(dd / "v1" / "film.json", {"title": "Red Car", "shots": [{"id": "hook", "t0": 0, "t1": 3.3,
                                                                       "scene": "kit:pixel/HOOK"}]})
    write_json(dd / "calls" / "01-treatment.meta.json", {"ok": True, "seconds": 70.5,
                                                         "usage": {"input_tokens": 1000, "output_tokens": 200}})
    write_json(dd / "calls" / "02-film.meta.json", {"ok": False, "seconds": 10,
                                                    "usage": {"input_tokens": 50, "output_tokens": 5}})
    lines = [
        '{"t": 0.0, "step": "setup", "msg": "Director ready", "level": "info"}',
        '{"t": 1.0, "step": "treatment", "msg": "Treatment: A car levels up", "level": "info", "acts": ["Act 1"]}',
        '{"t": 2.0, "step": "scenes", "msg": "Coding scene boss-fight", "level": "info"}',
        '{"t": 2.0, "step": "scenes", "msg": "Coding scene petal-bloom", "level": "info"}',
        'not json',
        '{"t": 9.0, "step": "critic", "msg": "Critic round 1: reviewing", "level": "info", "sheets": ["'
        + str(sheet).replace("\\", "\\\\") + '", "C:\\\\elsewhere\\\\contact-9.jpg"]}',
        '{"t": 9.5, "step": "film", "msg": "debug detail", "level": "debug"}',
    ]
    (dd / "log.jsonl").write_bytes(("\r\n".join(lines) + "\r\n" + '{"t": 10, "step": "cri').encode("utf-8"))
    return job["id"], dd


def test_director_log_reads_incrementally_and_summarises(api: dict[str, Any]) -> None:
    c = api["client"]
    jid, dd = _director_job(api)
    r = c.get(f"{P}/jobs/{jid}/director-log").json()
    assert r["directed"] and r["available"] and r["direction"].startswith("pixel")
    steps = [e["step"] for e in r["entries"]]
    assert steps == ["setup", "treatment", "scenes", "scenes", "critic", "film"]     # bad line skipped
    assert r["next"] == 7                                                            # partial line not consumed
    critic = r["entries"][4]
    assert critic["sheets"] == [{"v": 1, "name": "contact-1.jpg"}]                   # outside paths dropped
    assert "C:" not in str(critic)
    assert r["treatment"]["title"] == "Red Car" and r["treatment"]["acts"][0]["style"] == "pixel"
    assert r["coding"] == ["petal-bloom"]                                            # boss-fight is coded
    v1 = r["versions"][0]
    assert v1["n"] == 1 and v1["scenes"][0]["name"] == "boss-fight" and v1["sheets"] == ["contact-1.jpg"]
    assert v1["score"]["min"] == 4 and abs(v1["score"]["mean"] - 5.14) < 0.01 and v1["keyframes"] == 1
    assert v1["shots"][0]["scene"] == "kit:pixel/HOOK"
    assert r["usage"] == {"calls": 2, "ok": 1, "input_tokens": 1050, "output_tokens": 205, "seconds": 80.5}
    assert r["bar"] == 8.0 and len(r["rubric"]) == 7
    # the runner finishes the line; the next poll gets exactly that line
    with (dd / "log.jsonl").open("ab") as f:
        f.write(b'tic", "msg": "Scores v1", "level": "info", "scores": {"legibility": 4}}\n')
    more = c.get(f"{P}/jobs/{jid}/director-log", params={"since": r["next"]}).json()
    assert [e["msg"] for e in more["entries"]] == ["Scores v1"] and more["entries"][0]["scores"] == {"legibility": 4}
    assert more["next"] == 8 and more["coding"] == ["petal-bloom"]


def test_director_log_of_a_quick_job_is_empty(api: dict[str, Any]) -> None:
    job = api["store"].create("s1", {})
    r = api["client"].get(f"{P}/jobs/{job['id']}/director-log").json()
    assert r["directed"] is False and r["available"] is False and r["entries"] == [] and r["versions"] == []


def test_director_images_are_downscaled_and_confined(api: dict[str, Any]) -> None:
    c = api["client"]
    jid, _ = _director_job(api)
    r = c.get(f"{P}/jobs/{jid}/director/image", params={"v": 1, "name": "contact-1.jpg", "w": 480}).json()
    assert r["url"].startswith("data:image/jpeg;base64,") and r["w"] == 480 and r["h"] == 270
    k = c.get(f"{P}/jobs/{jid}/director/image", params={"v": 1, "name": "01-hook.png"}).json()
    assert k["w"] == 320
    for bad in ("../job.json", "contact-1.jpg/../../job.json", "job.json", "01-hook.png/../../x.png", ""):
        assert c.get(f"{P}/jobs/{jid}/director/image", params={"v": 1, "name": bad}).status_code == 404
    assert c.get(f"{P}/jobs/{jid}/director/image", params={"v": 2, "name": "contact-1.jpg"}).status_code == 404


def test_director_scene_code_peek(api: dict[str, Any]) -> None:
    c = api["client"]
    jid, _ = _director_job(api)
    r = c.get(f"{P}/jobs/{jid}/director/scene", params={"v": 1, "name": "boss-fight"}).json()
    assert r["code"].startswith("sr.defineScene") and r["lines"] == 3 and not r["truncated"]
    for bad in ("../../job", "boss-fight.js", "nope"):
        assert c.get(f"{P}/jobs/{jid}/director/scene", params={"v": 1, "name": bad}).status_code == 404


# --------------------------------------------------------------------------------- result helpers


def test_post_text_for_quick_and_directed_films(api: dict[str, Any]) -> None:
    store, c = api["store"], api["client"]
    quick = store.create("s1", {"style": "pixel", "mode": "speedrun", "seconds": 60})
    store.update(quick["id"], stage="done", title="Tiny Todo", duration_s=58.2,
                 storyboard={"title": "Tiny Todo", "tagline": "Todos in one keystroke", "scenes": []})
    text = c.get(f"{P}/jobs/{quick['id']}/post-text").json()["text"]
    assert text.startswith("Tiny Todo: Todos in one keystroke") and "speedrun" in text and "(pixel, 58 s)" in text
    assert text.endswith("#HermesAgent #Hype") and len(text) <= 280
    directed = store.create("s1", {"direction": "anime finale"}, kind="directed")
    store.update(directed["id"], stage="done", title="Red Car")
    write_json(store.job_dir(directed["id"]) / "director" / "treatment.json", {"logline": "A car levels up."})
    text = c.get(f"{P}/jobs/{directed['id']}/post-text").json()["text"]
    assert text.startswith("Red Car: A car levels up.") and "Directed from one line of text" in text
    long = store.create("s1", {})
    store.update(long["id"], stage="done", title="T", storyboard={"tagline": "word " * 200, "scenes": []})
    assert len(c.get(f"{P}/jobs/{long['id']}/post-text").json()["text"]) <= 280


def test_library_lists_saved_scenes_newest_first(api: dict[str, Any]) -> None:
    lib = api["data"] / "library"
    write_json(lib / "boss-battle" / "meta.json", {"id": "lib:boss-battle", "name": "boss-battle",
                                                   "describe": "A pixel boss fight", "layer": "2d",
                                                   "scores": {"composition": 6, "legibility": 8},
                                                   "params": {"boss_name": {}, "menu": {}}, "created_job": "j1"})
    jpeg(lib / "boss-battle" / "thumb.jpg", (96, 54))
    time.sleep(0.02)
    write_json(lib / "worlds" / "flower-field" / "meta.json", {"describe": "Anime meadow at sunset"})
    (lib / "broken").mkdir()
    (lib / "broken" / "meta.json").write_text("{not json", encoding="utf-8")
    r = api["client"].get(f"{P}/library").json()
    items = r["items"]
    assert [i["name"] for i in items] == ["flower-field", "boss-battle"] and r["dir"].endswith("library")
    flower, boss = items
    assert flower["kind"] == "world" and flower["id"] == "lib:flower-field" and flower["thumb"] == ""
    assert boss["thumb"].startswith("data:image/jpeg") and boss["score"] == 7.0 and boss["params"] == ["boss_name", "menu"]


def test_library_is_empty_before_any_directed_film(api: dict[str, Any]) -> None:
    assert api["client"].get(f"{P}/library").json()["items"] == []


# ------------------------------------------------------------------------------- preset customization (W5)


def test_post_job_with_a_preset_customization(api: dict[str, Any]) -> None:
    store, c = api["store"], api["client"]
    r = c.post(f"{P}/jobs", json={"session_id": "s-cz", "options": {"style": "comic"},
                                  "customize": {"text": "the villain is a swarm of bugs",
                                                "knobs": {"accent": "cyan", "energy": "high"}}})
    assert r.status_code == 200, r.text
    job = store.load(r.json()["id"])
    cz = job["options"]["hints"]["customize"]
    assert job["kind"] == "quick" and job["options"]["direction"] == ""
    assert cz["route"] == "customize" and cz["text"] == "the villain is a swarm of bugs"
    assert cz["knobs"] == {"accent": "#00E5FF", "energy": "high"}
    # a request the preset cannot make goes to the Director, starting from the preset
    r = c.post(f"{P}/jobs", json={"session_id": "s-cz2", "options": {"style": "pixel"},
                                  "customize": {"text": "transition into a different style mid way through"}})
    assert r.status_code == 200 and store.load(r.json()["id"])["kind"] == "directed"
    bad = c.post(f"{P}/jobs", json={"session_id": "s-cz3", "customize": {"knobs": {"colr": "red"}}})
    assert bad.status_code == 400 and "Valid settings" in bad.text


def test_customize_vocabulary(api: dict[str, Any]) -> None:
    v = api["client"].get(f"{P}/customize").json()
    assert "neon" in v["palettes"] and "Bangers" in v["fonts"] and v["energies"] == ["calm", "normal", "high"]
    assert "whisper" in v["voices"] and "playful" in v["moods"] and any(b["id"] == "comic_b" for b in v["beds"])
    assert {"accent", "music", "logo", "language"} <= set(v["knobs"])


# ------------------------------------------------------------------------------- Blender install (optional)

def _missing_blender(api: dict[str, Any], monkeypatch: Any) -> Any:
    loc = api["mod"]._sub("blender.locate")
    monkeypatch.setattr(loc, "locate", lambda *a, **k: loc.BlenderMissing("not_found", "Blender was not found."))
    bi = api["mod"]._sub("blender.install")
    monkeypatch.setattr(bi, "_STATE", bi._State())
    return bi


def test_blender_status_offers_the_pinned_build(api: dict[str, Any], monkeypatch: Any) -> None:
    bi = _missing_blender(api, monkeypatch)
    got = api["client"].get(f"{P}/blender").json()
    assert got["found"] is False and got["install"] == {"state": "idle"} and "not found" in got["message"]
    want = bi.build_for()
    if want is not None:
        assert got["offer"]["version"] == want.version and got["offer"]["size_mb"] == want.size_mb
        assert got["offer"]["url"].startswith("https://download.blender.org/")


def test_blender_install_needs_an_explicit_confirm(api: dict[str, Any], monkeypatch: Any) -> None:
    bi = _missing_blender(api, monkeypatch)
    started: list[dict[str, Any]] = []
    monkeypatch.setattr(bi, "start_background", lambda **kw: started.append(kw) or {"state": "running"})
    c = api["client"]
    assert c.post(f"{P}/blender/install", json={}).status_code == 400
    assert c.post(f"{P}/blender/install", json={"confirm": "yes"}).status_code == 400
    assert started == []
    if bi.build_for() is None:
        return
    assert c.post(f"{P}/blender/install", json={"confirm": True}).status_code == 202 and len(started) == 1


def test_blender_install_route_reports_progress_then_done(api: dict[str, Any], monkeypatch: Any,
                                                         tmp_path: Path) -> None:
    import hashlib
    import io
    import threading
    import zipfile
    bi = _missing_blender(api, monkeypatch)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("blender-9.9.9-windows-x64/blender.exe", b"fake")
    data = buf.getvalue()
    build = bi.Build("windows-x64", "9.9.9", "blender-9.9.9-windows-x64.zip", hashlib.sha256(data).hexdigest(),
                     len(data), url="https://example.invalid/b.zip")
    gate = threading.Event()

    class Resp(io.BytesIO):
        headers = {"Content-Length": str(len(data))}

        def read(self, n: int = -1) -> bytes:
            gate.wait(5)                 # hold the download so the route can see it running
            return super().read(n)

    real_start = bi.start_background
    monkeypatch.setattr(bi, "build_for", lambda key=None: build)
    monkeypatch.setattr(bi, "start_background", lambda **kw: real_start(
        build=build, parent=tmp_path / "apps", opener=lambda req, t: Resp(data),
        probe=lambda exe: "9.9.9" if exe.is_file() else None, disk_free=lambda p: 10 ** 12))
    c = api["client"]
    first = c.post(f"{P}/blender/install", json={"confirm": True})
    assert first.status_code == 202 and first.json()["install"]["state"] == "running"
    assert first.json()["install"]["version"] == "9.9.9"
    again = c.post(f"{P}/blender/install", json={"confirm": True}).json()     # a second click joins the first
    assert again["install"]["state"] == "running"
    gate.set()
    for _ in range(250):
        st = c.get(f"{P}/blender").json()["install"]
        if st["state"] != "running":
            break
        time.sleep(0.02)
    assert st["state"] == "done" and st["pct"] == 100, st
    assert Path(st["path"]).is_file() and Path(st["path"]).parent.name == "Blender 9.9"
