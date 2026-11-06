"""The pipeline's designed cue-sheet path (``deps.fit_cue_sheet``): one call for the whole ``film.music``, stings
rendered into the music are not placed again as SFX, and a failure falls back to per-bed crossfades."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from showreel_core.pipeline import run_job

from .conftest import Recorder, make_deps
from .test_pipeline_e2e import _host, _job

MUSIC = [{"bed": "pixel_boss", "t0": 0, "t1": 10}, {"sting": "bloom_riser", "t": 9.6},
         {"bed": "dream", "t0": 10, "t1": 20}]


def _director(vo: Path) -> Any:
    def director(*, job_dir: Path, **_: Any) -> dict:
        film = {"version": 1, "fps": 30, "size": [1920, 1080], "dur": 20.0, "title": "Red Car",
                "shots": [{"id": "a", "t0": 0, "t1": 10, "scene": "kit:pixel/x"},
                          {"id": "b", "t0": 10, "t1": 20, "scene": "kit:nature/y"}],
                "music": MUSIC, "cues": [{"t": 3.0, "sfx": "slash"}],
                "narration": [{"path": str(vo), "start": 12.0, "duration": 4.5, "text": "Now it is real."}]}
        return {"ok": True, "status": "done", "film": film, "job_dir": str(job_dir)}
    return director


def test_designed_cue_sheet_renders_stings_once(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    vo = Path(env["tmp"]) / "vo.wav"
    vo.write_bytes(b"RIFFvo")
    calls: list[dict[str, Any]] = []
    placed: list[list[Any]] = []

    def fit_cue_sheet(music: list[dict[str, Any]], dur: float, out: Path, **kw: Any) -> Any:
        calls.append({"music": music, "dur": dur, **kw})
        out.write_bytes(b"RIFFsheet")
        seg = type("Seg", (), {"bed_id": "pixel_boss_a", "join_out": "sting"})()
        return type("Sheet", (), {"path": out, "segments": [seg], "warnings": [],
                                  "consumed": [{"sting": "bloom_riser", "t": 9.6}]})()

    def place_sfx(cues: list[Any], duration: float, style: str, fps: int) -> tuple[list[Any], list[str]]:
        placed.append(list(cues))
        return [{"cue": c} for c in cues], []

    job = _job(store, seconds=30, direction="pixel boss fight then a meadow")
    deps = make_deps(rec, director=_director(vo), fit_cue_sheet=fit_cue_sheet, place_sfx=place_sfx)
    final = run_job(job["id"], _host()[0], store=store, deps=deps)
    assert final["stage"] == "done", final.get("error")
    assert len(calls) == 1 and calls[0]["music"] == MUSIC and calls[0]["dur"] == 20.0
    assert calls[0]["last_word_time"] == 16.5 and "seed" in calls[0] and "style" in calls[0]
    names = [c["sfx"] for c in placed[0]]
    assert "slash" in names and "bloom_riser" not in names               # the sting lives in the music track
    assert "join_music" not in rec.calls
    assert any("designed joins" in str(e.get("msg", "")) for e in final.get("log", []))


def test_designed_cue_sheet_failure_falls_back_to_crossfades(env: dict[str, Any]) -> None:
    store, rec = env["store"], Recorder()
    vo = Path(env["tmp"]) / "vo.wav"
    vo.write_bytes(b"RIFFvo")

    def broken(*a: Any, **k: Any) -> Any:
        raise RuntimeError("no beds")

    job = _job(store, seconds=30, direction="pixel boss fight then a meadow")
    final = run_job(job["id"], _host()[0], store=store,
                    deps=make_deps(rec, director=_director(vo), fit_cue_sheet=broken))
    assert final["stage"] == "done", final.get("error")
    assert rec.calls["join_music"] == [{"parts": 2, "xfade": 0.6}]
    assert rec.calls["place_sfx"] == [3]                                  # slash, page whoosh + the sting
