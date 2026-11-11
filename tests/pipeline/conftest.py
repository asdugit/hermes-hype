"""Shared fakes for pipeline tests: every Chromium/ffmpeg/TTS stage is replaced, story + timing stay real."""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from showreel_core.contracts import Event, Product, Stats
from showreel_core.jobs import JobStore
from showreel_core.pipeline import Deps, SavedSession

FIXTURES = Path(__file__).resolve().parents[1] / "story" / "fixtures"


def load_bundle(name: str = "webapp_session.json", session_id: str = "sess-1") -> SavedSession:
    raw = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    events = [Event(**{k: v for k, v in e.items() if k in Event.__dataclass_fields__}) for e in raw["events"]]
    stats = Stats(**{k: v for k, v in (raw.get("stats") or {}).items() if k in Stats.__dataclass_fields__})
    prod = raw.get("product") or {}
    product = Product(**{k: v for k, v in prod.items() if k in Product.__dataclass_fields__})
    return SavedSession(session_id, events, stats, str(raw.get("digest") or ""), product, bool(prod))


@dataclass
class FakeClip:
    path: Path
    duration: float
    text: str
    provider: str = "fake"


@dataclass
class FakeRender:
    ok: bool
    out_path: str | None = None
    error: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "out_path": self.out_path, "error": self.error, "frames": 1, "warnings": self.warnings}


@dataclass
class FakeBed:
    id: str = "launch_a"
    bpm: float = 124.0


@dataclass
class Recorder:
    calls: dict[str, list[Any]] = field(default_factory=dict)

    def add(self, name: str, item: Any) -> None:
        self.calls.setdefault(name, []).append(item)

    def n(self, name: str) -> int:
        return len(self.calls.get(name, []))


def make_deps(rec: Recorder, *, bundle: SavedSession | None = None, render_fail: int = 0, tts_fail: bool = False,
              mix_fail: int = 0, on_render: Any = None, director: Any = None, **overrides: Any) -> Deps:
    """Deps whose heavy stages write small fake files; ``render_fail`` = how many render calls fail first."""
    bundle = bundle or load_bundle()
    state = {"render_fail": render_fail, "mix_fail": mix_fail}

    def read_session(session_id: str, *, assets_dir: Path, redact: bool) -> Any:
        rec.add("read_session", session_id)
        return bundle

    def tts(dispatch: Any, text: str, out_path: Path, speed: float | None = None) -> Any:
        rec.add("tts", {"text": text, "speed": speed})
        if tts_fail:
            return None
        Path(out_path).write_bytes(b"RIFFfake")
        return FakeClip(Path(out_path), round(len(text.split()) / 2.6, 3), text)

    def quick_film(tl: Any, **kw: Any) -> dict[str, Any]:
        rec.add("quick_film", {"style": kw["style"], "aspect": kw["aspect"], "dur": tl.dur})
        if kw["style"] in overrides.get("broken_styles", ()):
            raise RuntimeError(f"style {kw['style']} is broken")
        return {"film": {"version": 1, "fps": tl.fps, "size": [tl.w, tl.h], "dur": tl.dur, "title": tl.title,
                         "shots": [{"id": f"s{sc.i}", "t0": sc.t0, "t1": sc.t1, "scene": "kit:base/card"}
                                   for sc in tl.scenes]}, "assets": {}, "scenes": {}}

    def build_page(film: dict[str, Any], *, page_dir: Path, job_dir: Path, assets: Any = None,
                   scenes: Any = None) -> str:
        rec.add("build_page", page_dir)
        (page_dir / "stage.html").write_text("<!doctype html>", encoding="utf-8")
        (page_dir / "film.json").write_text(json.dumps(film), encoding="utf-8")
        return "stage.html"

    def layout_qa(built: Any, times: list[float], thumbs_dir: Path | None) -> dict[str, Any]:
        rec.add("layout_qa", built.aspect)
        thumbs = []
        if thumbs_dir is not None:
            thumbs_dir.mkdir(parents=True, exist_ok=True)
            thumbs = [str(thumbs_dir / "t0.jpg")]
            Path(thumbs[0]).write_bytes(b"\xff\xd8fake")
        return {"issues": [], "cues": [{"t": 1.0, "sfx": "whoosh"}], "errors": [], "thumbs": thumbs}

    def render(spec: Any, progress: Any, cancel: Any) -> Any:
        rec.add("render", {"gpu": spec.gpu, "workers": spec.workers, "w": spec.w, "h": spec.h, "fps": spec.fps})
        if on_render is not None:
            on_render(spec, progress, cancel)
        if cancel.is_set():
            return FakeRender(False, error={"code": "cancelled", "message": "cancelled"})
        if state["render_fail"] > 0:
            state["render_fail"] -= 1
            return FakeRender(False, error={"code": "chunk_failed", "message": "boom"})
        total = max(1, round(spec.duration_s * spec.fps))
        progress(total // 2, total, 5.0)
        progress(total, total, 0.0)
        Path(spec.out_path).write_bytes(b"\x00\x00\x00\x18ftypmp42fake-video")
        return FakeRender(True, str(spec.out_path))

    def fit_music(bed: Any, duration: float, out: Path, drop: Any, last: Any) -> Any:
        rec.add("fit_music", {"bed": bed.id, "dur": duration, "drop": drop, "last": last})
        out.write_bytes(b"RIFFmusic")
        return type("Fitted", (), {"path": out, "bed_id": bed.id, "bpm": bed.bpm, "warnings": []})()

    def place_sfx(cues: list[Any], duration: float, style: str, fps: int) -> tuple[list[Any], list[str]]:
        rec.add("place_sfx", len(cues))
        return [{"cue": c} for c in cues], []

    def mix(out: Path, duration: float, *, music: Any, voices: list[Any], sfx: list[Any], work_dir: Path) -> Any:
        rec.add("mix", {"music": music is not None, "voices": len(voices), "sfx": len(sfx)})
        if state["mix_fail"] > 0:
            state["mix_fail"] -= 1
            raise RuntimeError("mix exploded")
        out.write_bytes(b"RIFFmix")
        return type("Mix", (), {"path": out, "voice_stem": None, "bed_stem": None})()

    def mux(video: Path, audio: Path, out: Path, dur: float) -> Path:
        rec.add("mux", out)
        shutil.copy2(video, out)
        return out

    def check_video(path: Path, *, frames: int, dur: float, fps: int, times: list[float], labels: list[str],
                    allowed_black=(),
                    contact_sheet: Path) -> dict[str, Any]:
        rec.add("check_video", {"frames": frames, "dur": dur})
        contact_sheet.write_bytes(b"\x89PNGfake")
        return {"ok": True, "issues": [], "contact_sheet": str(contact_sheet), "frames": frames}

    def capture(product: Any, events: list[Any], out_dir: Path, *, budget_s: float, progress: Any, cancel: Any) -> list:
        rec.add("capture", {"product": getattr(product, "name", ""), "events": len(events), "budget_s": budget_s})
        return []

    deps = Deps(read_session=read_session, tts=tts, pick_bed=lambda style, seed, bed_id=None: FakeBed(),
                quick_film=quick_film, build_page=build_page, layout_qa=layout_qa, render=render,
                fit_music=fit_music, place_sfx=place_sfx, mix=mix, audio_report=lambda *a, **k: {"ok": True},
                mux=mux, check_video=check_video, speed_check=lambda speed: None,
                director=(lambda: director), capture=capture, gpu_ok=lambda cache: True, fit_cue_sheet=None,
                join_music=lambda parts, xfade, out: (rec.add("join_music", {"parts": len(parts), "xfade": xfade}),
                                                      Path(out).write_bytes(b"RIFFjoined"))[1] and out)
    for k, v in overrides.items():
        if hasattr(deps, k):
            setattr(deps, k, v)
    return deps


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Isolated job store + delivery folder."""
    data, videos = tmp_path / "data", tmp_path / "videos"
    monkeypatch.setenv("SHOWREEL_DATA_DIR", str(data))
    monkeypatch.setenv("SHOWREEL_VIDEOS_DIR", str(videos))
    return {"store": JobStore(data), "videos": videos, "tmp": tmp_path}
