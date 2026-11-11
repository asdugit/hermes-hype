"""Product inference: web app, media deliverables, plain chat (no product)."""
import json

from session_synth import Transcript, untrusted

from showreel_core.session import analyze_rows, extract_events, infer_product

INDEX = """<!doctype html>
<html><head><title>Tide Clock</title>
<meta name="description" content="A tide clock for surfers that shows the next high tide at a glance.">
</head><body><h2>Live tide curve</h2><h3>Moon phase</h3><script src="app.js"></script></body></html>
"""
README = """# Tide Clock

A tiny web app that shows when the next high tide arrives. Works offline.

## Features
- Live tide curve
- Moon phase overlay
- Works offline: a service worker caches the data
"""
PKG = json.dumps({"name": "tide-clock", "description": "Tide times at a glance", "scripts": {"dev": "vite"},
                  "dependencies": {"vite": "^5"}})


def web_app_rows(tmp_path):
    site = tmp_path / "tide-clock"
    site.mkdir()
    (site / "index.html").write_text(INDEX, encoding="utf-8")
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    t = Transcript().user("Build me a tide clock web app")
    t.call("write_file", {"path": str(site / "index.html"), "content": INDEX}, {"bytes_written": len(INDEX)})
    t.call("write_file", {"path": str(site / "README.md"), "content": README}, {"bytes_written": len(README)})
    t.call("write_file", {"path": str(site / "package.json"), "content": PKG}, {"bytes_written": len(PKG)})
    t.call("terminal", {"command": f"cd {site} && npm run dev", "background": True},
           {"output": "\n  VITE v5.0.0  ready in 300 ms\n\n  ➜  Local:   http://localhost:5173/\n", "exit_code": None,
            "session_id": "proc_1", "pid": 7})
    code = '# Looking at the running app\nnew_tab("http://localhost:5173/")\nprint(capture_screenshot())'
    t.call("browser_exec", {"code": code},
           untrusted("browser_exec", json.dumps({"success": True, "output": str(shot).replace("\\", "\\\\") + "\n"})))
    t.say(f"Done — open {site / 'index.html'} or run `npm run dev`.")
    return t.rows


def test_web_app_product_and_artifacts(tmp_path):
    events = extract_events(web_app_rows(tmp_path)).events
    rep = infer_product(events)
    p = rep.product
    assert rep.detected and rep.confidence >= 0.7
    assert p.name == "Tide Clock"                                   # README H1 outranks package name
    names = [n["name"] for n in rep.evidence["names"]]
    assert "tide-clock" in names and "Tide Clock" in names
    assert p.one_liner.startswith("A tiny web app")
    assert p.kind == "web_app"
    assert p.urls[0] == "http://localhost:5173"                    # trailing "/" trimmed (still a verbatim substring)
    assert p.run_commands and p.run_commands[0].startswith("npm run dev")
    assert any(e.endswith("index.html") for e in p.entry_files)
    assert p.features[:2] == ["Live tide curve", "Moon phase overlay"]
    arts = [e for e in events if e.kind == "artifact"]
    web = [a for a in arts if a.data["kind"] == "web"]
    assert web and web[0].data["exists"] and web[0].data["title"] == "Tide Clock" and web[0].weight >= 0.95
    shot = next(e for e in events if e.kind == "screenshot")
    assert shot.data["product_shot"] and shot.weight >= 0.9
    assert set(p.hero_event_ids) >= {web[0].id, shot.id}
    assert [e.id for e in events] == [f"e{i}" for i in range(len(events))]
    for a in arts:                                                  # artifact sits right after its source event
        src_idx = int(a.data["ref_ids"][-1][1:])
        assert src_idx < int(a.id[1:])


def test_media_deliverables_from_final_answer_and_saved_output(tmp_path):
    vid = tmp_path / "out" / "trailer.mp4"
    vid.parent.mkdir()
    vid.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    still = tmp_path / "out" / "still.png"
    still.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    t = Transcript().user("render the trailer")
    t.call("terminal", {"command": "ffmpeg -i in.mov out/poster.png"},
           {"output": f"Saved poster to out/poster.png\nwrote {still}\n", "exit_code": 0})
    t.say(f"Here you go:\nMEDIA:{vid}")
    events = extract_events(t.rows).events
    rep = infer_product(events)
    arts = {e.data["kind"]: e for e in events if e.kind == "artifact"}
    assert arts["video"].data["delivered"] and arts["video"].data["exists"]
    assert arts["image"].data["source"] == "saved by command" and arts["image"].data["exists"]
    assert not any(a.data["path"].endswith("poster.png") for a in arts.values())   # unverifiable mention dropped
    assert rep.product.kind == "media" and rep.detected


def test_chat_only_session_has_no_product():
    t = Transcript().user("What's the capital of France?").say("Paris.")
    rep = infer_product(extract_events(t.rows).events)
    assert not rep.detected and rep.product.urls == [] and rep.product.kind == ""


def test_deployed_url_and_digest_section(tmp_path):
    rows = web_app_rows(tmp_path)
    t = Transcript(t0=rows[-1]["timestamp"])
    t.call("terminal", {"command": "npx vercel --prod"},
           {"output": "✅  Production: https://tide-clock.vercel.app [3s]\n", "exit_code": 0})
    b = analyze_rows(rows + t.rows, {"title": "tide"}, assets_dir=tmp_path / "assets")
    assert b.product.urls[0] == "https://tide-clock.vercel.app"
    assert "## PRODUCT EVIDENCE" in b.digest
    assert b.digest.index("## PRODUCT EVIDENCE") < b.digest.index("## FIRST REQUEST")
    assert "Tide Clock" in b.digest
    web = next(e for e in b.events if e.kind == "artifact" and e.data["kind"] == "web")
    assert "tide-clock" in web.data["path"] and web.data["path"].count(str(tmp_path)) <= 1


def test_template_default_names_never_name_the_product():
    """Audit 2026-11-11: create-next-app's package name "my-app" (score 0.85) beat the project folder, so the film
    was titled "my-app"; template names stay only as a last resort and still count as product evidence."""
    t = Transcript()
    t.user("build a little shop")
    t.call("write_file", {"path": "/home/bob/shop/app/layout.tsx",
                          "content": 'export const metadata = { title: "Create Next App" }'}, {"bytes_written": 50})
    t.call("write_file", {"path": "/home/bob/shop/package.json",
                          "content": json.dumps({"name": "my-app", "scripts": {"dev": "next dev"}})}, {"bytes_written": 60})
    t.call("write_file", {"path": "/home/bob/shop/index.html",
                          "content": "<html><head><title>Vite + React + TS</title></head></html>"}, {"bytes_written": 60})
    t.say("Done.")
    rep = infer_product(extract_events(t.rows).events, {})
    assert rep.product.name == "shop" and rep.detected
    t2 = Transcript()
    t2.call("write_file", {"path": "/home/bob/x/package.json", "content": json.dumps({"name": "vite-project"})},
            {"bytes_written": 30})
    assert infer_product(extract_events(t2.rows).events, {}).product.name in ("x", "vite-project")


def test_holder_folders_and_the_login_name_never_name_the_product(monkeypatch):
    """Audit 2026-11-11: files written straight into D:/<login>/ or ~/Desktop named the product after the
    folder: the user's own login name (or "Desktop") as the film's title."""
    import getpass
    monkeypatch.setattr(getpass, "getuser", lambda: "alice")
    for folder in ("D:/alice", "/home/bob/Desktop", "C:/Users/bob/AppData/Local/Temp/tmpab12x"):
        t = Transcript()
        t.call("write_file", {"path": f"{folder}/game.py", "content": "import pygame\n"}, {"bytes_written": 14})
        t.call("write_file", {"path": f"{folder}/level.py", "content": "LEVEL = 1\n"}, {"bytes_written": 10})
        names = [c["name"].lower() for c in infer_product(extract_events(t.rows).events, {}).evidence.get("names", [])]
        assert not {"alice", "desktop", "tmpab12x"} & set(names), (folder, names)
    t = Transcript()
    t.call("write_file", {"path": "D:/alice/orbit-quest/game.py", "content": "x = 1\n"}, {"bytes_written": 6})
    t.call("write_file", {"path": "D:/alice/orbit-quest/level.py", "content": "y = 2\n"}, {"bytes_written": 6})
    assert infer_product(extract_events(t.rows).events, {}).product.name == "orbit-quest"
