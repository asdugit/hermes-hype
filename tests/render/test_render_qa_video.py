"""qa/video.py: black detection parsing and checks on synthetic ffmpeg-generated videos."""
from __future__ import annotations

import subprocess
from pathlib import Path

from showreel_core.qa import video as V

BLACK_LOG = """[blackdetect @ 0000] black_start:0 black_end:1.5 black_duration:1.5
frame=  100 fps=0.0 q=-0.0 size=N/A
[blackdetect @ 0000] black_start:3.2 black_end:4.0 black_duration:0.8
"""


def test_parse_blackdetect():
    assert V.parse_blackdetect(BLACK_LOG) == [(0.0, 1.5), (3.2, 4.0)]
    assert V.parse_blackdetect("nothing here") == []


def _make(ffmpeg: str, out: Path) -> None:
    """1 s black then 1 s test pattern, 320x180@30, BT.709-tagged H.264 (or VP9)."""
    from showreel_core.render.ffmpeg import capabilities, encoder_spec, pick_encoder

    enc = encoder_spec(pick_encoder(capabilities(ffmpeg)), 320, 180, 30)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=320x180:r=30:d=1",
           "-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=1", "-filter_complex",
           "[0:v][1:v]concat=n=2:v=1,format=yuv420p,setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
           ":range=tv[v]", "-map", "[v]", *enc.args, "-y", str(out)]
    subprocess.run(cmd, check=True, capture_output=True)


def test_check_video_on_synthetic(ffmpeg_path, tmp_path):
    vid = tmp_path / "v.mp4"
    _make(ffmpeg_path, vid)
    rep = V.check_video(vid, expected_frames=60, expected_duration_s=2.0, fps=30, scene_times=[0.5, 1.5],
                        scene_labels=["black", "pattern"], contact_sheet=tmp_path / "sheet.png", ffmpeg=ffmpeg_path)
    assert rep.error is None, rep.error
    assert rep.ok and rep.frames == 60 and (rep.width, rep.height) == (320, 180)
    kinds = {i["kind"] for i in rep.issues}
    assert "black" in kinds and "frame0_dark" in kinds          # warnings, not errors
    assert rep.black_segments and rep.black_segments[0][0] == 0.0
    assert rep.frame0_luma is not None and rep.frame0_luma < 20
    assert rep.contact_sheet and Path(rep.contact_sheet).is_file()
    from PIL import Image
    assert Image.open(rep.contact_sheet).width > 2 * 480


def test_check_video_flags_frame_mismatch_and_allows_designed_black(ffmpeg_path, tmp_path):
    vid = tmp_path / "v.mp4"
    _make(ffmpeg_path, vid)
    rep = V.check_video(vid, expected_frames=61, ffmpeg=ffmpeg_path, allowed_black=[(0.0, 1.1)])
    assert not rep.ok
    kinds = {i["kind"] for i in rep.issues}
    assert "frame_count" in kinds and "black" not in kinds


def test_check_video_never_raises(tmp_path):
    rep = V.check_video(tmp_path / "missing.mp4", ffmpeg=str(tmp_path / "no-ffmpeg"))
    assert not rep.ok and rep.error is not None


def test_transition_windows_cover_a_designed_dark_cut_but_not_a_black_shot():
    film = {"transitions": [{"from": "a", "to": "b", "type": "kit:terminal/channel-switch", "t": 27.12, "dur": 0.3},
                            {"from": "b", "to": "c", "type": "crossfade", "t": "bad"}]}
    win = V.transition_windows(film)
    assert win == [(27.07, 28.17)]
    inside = lambda a, b: any(a >= lo - 1e-3 and b <= hi + 1e-3 for lo, hi in win)  # noqa: E731
    assert inside(27.366667, 28.033333)          # real E2E run 9: the CRT static into END
    assert not inside(27.4, 30.5)                # END itself black: still reported
    assert V.transition_windows(None) == [] and V.transition_windows({}) == []
