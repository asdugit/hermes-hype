"""A picture file that another session rewrote later is not this session's picture (synthetic files only)."""
from __future__ import annotations

import os
from pathlib import Path

from showreel_core.contracts import Event
from showreel_core.session.assets import STALE_SLACK_S, collect_assets

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (64).to_bytes(4, "big") + (40).to_bytes(4, "big")
       + b"\x08\x02\x00\x00\x00" + b"\x00" * 64)


def _shot(eid: str, t: float, src: Path) -> Event:
    return Event(eid, t, "screenshot", "browser_exec", src.name, "", {"src": str(src)})


def test_scratch_file_rewritten_after_the_session_is_not_used(tmp_path: Path) -> None:
    scratch = tmp_path / "harness" / "tmp" / "shot.png"          # one file for every screenshot of every session
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(PNG)
    t0 = 1_800_000_000.0
    os.utime(scratch, (t0 + 600 + STALE_SLACK_S + 200, t0 + 600 + STALE_SLACK_S + 200))   # rewritten later
    evs = [_shot("e1", 100.0, scratch), _shot("e2", 600.0, scratch)]
    rep = collect_assets(evs, tmp_path / "assets", base_dir=tmp_path / "project", session_t0=t0)
    assert rep.stale == 1 and rep.copied == 0
    assert all(e.data.get("missing") for e in evs)
    assert evs[1].data.get("stale") and evs[0].data.get("overwritten")


def test_fresh_scratch_file_only_shows_for_its_last_event(tmp_path: Path) -> None:
    scratch = tmp_path / "harness" / "shot.png"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(PNG)
    t0 = 1_800_000_000.0
    os.utime(scratch, (t0 + 605, t0 + 605))                       # written by the last screenshot call
    evs = [_shot("e1", 100.0, scratch), _shot("e2", 600.0, scratch)]
    rep = collect_assets(evs, tmp_path / "assets", base_dir=tmp_path / "project", session_t0=t0)
    assert rep.copied == 1 and rep.stale == 0
    assert evs[1].data.get("asset") and not evs[1].data.get("missing")
    assert evs[0].data.get("missing") and evs[0].data.get("overwritten")   # it showed an earlier state


def test_project_files_and_unknown_session_time_are_kept(tmp_path: Path) -> None:
    proj = tmp_path / "project"
    (proj / "charts").mkdir(parents=True)
    chart = proj / "charts" / "bills.png"
    chart.write_bytes(PNG)
    t0 = 1_800_000_000.0
    os.utime(chart, (t0 + 99_999, t0 + 99_999))                   # re-generated after the session: still the product
    ev = _shot("e1", 50.0, chart)
    assert collect_assets([ev], tmp_path / "a1", base_dir=proj, session_t0=t0).copied == 1
    other = tmp_path / "elsewhere.png"
    other.write_bytes(PNG)
    os.utime(other, (t0 + 99_999, t0 + 99_999))
    ev2 = _shot("e2", 50.0, other)
    assert collect_assets([ev2], tmp_path / "a2", base_dir=proj).copied == 1     # no session time: no guard
