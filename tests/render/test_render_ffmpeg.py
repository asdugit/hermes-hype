"""ffmpeg resolution, capability parsing, command builders and output parsing (no ffprobe)."""
from __future__ import annotations

from pathlib import Path

import pytest

from showreel_core.render import ffmpeg as ff
from showreel_core.render.errors import RenderError

ENCODERS_TXT = """Encoders:
 V..... = Video
 ------
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D libopenh264          OpenH264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)
 V....D h264_mf              H264 via MediaFoundation (codec h264)
 V....D libvpx-vp9           libvpx VP9 (codec vp9)
 A....D aac                  AAC (Advanced Audio Coding)
"""

FILTERS_TXT = """Filters:
  T.. = Timeline support
 ... blackdetect       V->V       Detect video intervals that are (almost) black.
 TS blend             VV->V      Blend two video frames into each other.
 .. paletteuse        VV->V      Use a palette to downsample an input video stream.
 TSC gblur             V->V       Apply Gaussian Blur filter.
 .. anoisesrc         |->A       Generate a noise audio signal.
"""

BANNER = """Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'out.mp4':
  Metadata:
    major_brand     : isom
  Duration: 00:01:12.03, start: 0.000000, bitrate: 5321 kb/s
  Stream #0:0[0x1](und): Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, progressive), 1920x1080 [SAR 1:1 DAR 16:9], 5100 kb/s, 30 fps, 30 tbr, 15360 tbn (default)
  Stream #0:1[0x2](und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 192 kb/s (default)
At least one output file must be specified
"""


def test_resolve_env_precedence(tmp_path):
    exe = tmp_path / "my ffmpeg.exe"
    exe.write_bytes(b"")
    exe.chmod(0o755)
    other = tmp_path / "other"
    other.write_bytes(b"")
    other.chmod(0o755)
    info = ff.resolve_ffmpeg({"HYPE_FFMPEG": str(exe), "FFMPEG_PATH": str(other)},
                             pm_lookup=lambda n: None, which=lambda n: None)
    assert (info.path, info.source) == (str(exe), "env")
    info = ff.resolve_ffmpeg({"FFMPEG_PATH": str(other)}, pm_lookup=lambda n: None, which=lambda n: None)
    assert info.path == str(other)


def test_resolve_bad_env():
    with pytest.raises(RenderError) as ei:
        ff.resolve_ffmpeg({"HYPE_FFMPEG": "/does/not/exist"}, pm_lookup=lambda n: None, which=lambda n: None)
    assert ei.value.code == "bad_env_ffmpeg"


def test_resolve_pm_then_path_then_error():
    assert ff.resolve_ffmpeg({}, pm_lookup=lambda n: Path("/pm/ffmpeg"), which=lambda n: "/usr/bin/ffmpeg").source == "pm"
    assert ff.resolve_ffmpeg({}, pm_lookup=lambda n: None, which=lambda n: "/usr/bin/ffmpeg").source == "path"
    with pytest.raises(RenderError) as ei:
        ff.resolve_ffmpeg({}, pm_lookup=lambda n: None, which=lambda n: None)
    assert ei.value.code == "no_ffmpeg" and "hermes pm install ffmpeg" in ei.value.hint


def test_parse_encoders_and_filters():
    enc = ff.parse_encoders(ENCODERS_TXT)
    assert {"libx264", "libopenh264", "h264_mf", "libvpx-vp9"} <= enc
    assert "aac" not in enc
    filt = ff.parse_filters(FILTERS_TXT)
    assert {"blackdetect", "blend", "paletteuse", "gblur"} <= filt
    assert "anoisesrc" not in filt


@pytest.mark.parametrize("name,container,needle", [
    ("libx264", "mp4", "-crf"), ("libopenh264", "mp4", "-b:v"), ("h264_mf", "mp4", "nv12"),
    ("h264_videotoolbox", "mp4", "-b:v"), ("libvpx-vp9", "webm", "-row-mt"),
])
def test_encoder_spec(name, container, needle):
    spec = ff.encoder_spec(name, 1920, 1080, 30)
    assert spec.container == container
    assert needle in spec.args
    assert spec.args[spec.args.index("-c:v") + 1] == name


def test_encoder_spec_x264_defaults_and_threads():
    a = ff.encoder_spec("libx264", 1920, 1080, 30, threads=4).args
    assert a[a.index("-preset") + 1] == "veryfast" and a[a.index("-crf") + 1] == "18"
    assert a[a.index("-pix_fmt") + 1] == "yuv420p" and a[a.index("-threads") + 1] == "4"
    with pytest.raises(ValueError):
        ff.encoder_spec("nope", 1, 1, 1)


def test_pick_encoder():
    caps = ff.Capabilities("ffmpeg", "v", frozenset(), frozenset(), ("libopenh264", "libvpx-vp9"))
    assert ff.pick_encoder(caps) == "libopenh264"
    assert ff.pick_encoder(caps, "libvpx-vp9") == "libvpx-vp9"
    assert ff.pick_encoder(caps, "libx264") == "libopenh264"
    with pytest.raises(RenderError) as ei:
        ff.pick_encoder(ff.Capabilities("ffmpeg", "v", frozenset(), frozenset(), ()))
    assert ei.value.code == "no_encoder"


def test_pick_encoder_smoke_tests_an_unprobed_preference(monkeypatch):
    caps = ff.Capabilities("ffmpeg", "v", frozenset({"libx264", "h264_mf"}), frozenset(), ("libx264",))
    monkeypatch.setattr(ff, "encoder_works", lambda path, name: name == "h264_mf")
    assert ff.pick_encoder(caps, "h264_mf") == "h264_mf"
    monkeypatch.setattr(ff, "encoder_works", lambda path, name: False)
    assert ff.pick_encoder(caps, "h264_mf") == "libx264"


def test_chunk_encode_cmd():
    enc = ff.encoder_spec("libx264", 1920, 1080, 30)
    cmd = ff.chunk_encode_cmd("ffmpeg", fps=30, out_path=Path("c 1.mp4"), enc=enc, filter_graph="[0:v]null[vout]",
                              extra_inputs=["-i", "pal.png"])
    s = " ".join(cmd)
    assert "-f image2pipe -framerate 30 -c:v mjpeg -i pipe:0 -i pal.png" in s
    assert "-filter_complex [0:v]null[vout] -map [vout]" in s
    assert "-colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv" in s
    assert "-progress pipe:1" in s and cmd[-1] == "c 1.mp4" and cmd[-4:-2] == ["-f", "mp4"]
    webm = ff.chunk_encode_cmd("ffmpeg", fps=29.97, out_path=Path("c.webm"),
                               enc=ff.encoder_spec("libvpx-vp9", 64, 64, 30), filter_graph="g", progress=False)
    assert "webm" in webm and "29.97" in webm and "-progress" not in webm


def test_concat_list_escapes(tmp_path):
    p = tmp_path / "it's ü" / "chunk_0000.mp4"
    p.parent.mkdir()
    lst = ff.write_concat_list([p], tmp_path / "l.txt")
    text = lst.read_text(encoding="utf-8")
    assert text.startswith("ffconcat version 1.0\n")
    assert "it'\\''s ü/chunk_0000.mp4'" in text and "\\chunk" not in text


def test_concat_and_mux_cmds():
    c = ff.concat_cmd("ffmpeg", Path("l.txt"), Path("o.mp4"))
    assert ["-c", "copy"] == c[c.index("-c"):c.index("-c") + 2] and "+faststart" in c
    m = ff.mux_cmd("ffmpeg", Path("v.mp4"), Path("a.wav"), Path("o.mp4"), duration_s=72.0)
    assert m[m.index("-c:a") + 1] == "aac" and m[m.index("-b:a") + 1] == "192k" and "+faststart" in m
    assert m[m.index("-t") + 1] == "72"
    w = ff.mux_cmd("ffmpeg", Path("v.webm"), Path("a.wav"), Path("o.webm"))
    assert w[w.index("-c:a") + 1] == "libopus" and "+faststart" not in w


def test_parse_media_info():
    info = ff.parse_media_info(BANNER)
    assert info.duration_s == pytest.approx(72.03)
    assert (info.video_codec, info.width, info.height, info.fps) == ("h264", 1920, 1080, 30.0)
    assert info.pix_fmt == "yuv420p" and info.color == "tv, bt709, progressive"
    assert (info.audio_codec, info.sample_rate) == ("aac", 48000)


def test_parse_progress_takes_last_values():
    text = "frame=10\nfps=0.0\nprogress=continue\nframe=150\nout_time=00:00:05.000000\nprogress=end\n"
    p = ff.parse_progress(text)
    assert p["frame"] == "150" and p["progress"] == "end"


def test_num_formatting():
    assert ff._num(30.0) == "30" and ff._num(29.97) == "29.97" and ff._num(15) == "15"


def test_real_ffmpeg_roundtrip(ffmpeg_path, tmp_path):
    """Encode 12 frames through the chunk command, then count/probe/extract without ffprobe."""
    import io
    import subprocess

    from PIL import Image

    caps = ff.capabilities(ffmpeg_path)
    assert caps.working, "no working encoder"
    frames = []
    for i in range(12):
        b = io.BytesIO()
        Image.new("RGB", (64, 36), (20 * i, 100, 200)).save(b, "JPEG", quality=92)
        frames.append(b.getvalue())
    enc = ff.encoder_spec(ff.pick_encoder(caps), 64, 36, 30)
    out = tmp_path / f"c.{enc.container}"
    cmd = ff.chunk_encode_cmd(ffmpeg_path, fps=30, out_path=out, enc=enc,
                              filter_graph="[0:v]scale=in_range=pc:in_color_matrix=bt601,format=gbrp,"
                                           "scale=out_range=tv:out_color_matrix=bt709,format=yuv420p,"
                                           "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709[vout]")
    p = subprocess.run(cmd, input=b"".join(frames), capture_output=True, check=False)
    assert p.returncode == 0, p.stderr.decode()[-500:]
    assert ff.parse_progress(p.stdout.decode())["frame"] == "12"
    assert ff.count_frames(ffmpeg_path, out) == 12
    assert ff.count_frames(ffmpeg_path, out, decode=False) == 12
    info = ff.media_info(ffmpeg_path, out)
    assert info.duration_s == pytest.approx(0.4, abs=0.04) and (info.width, info.height) == (64, 36)
    both = ff.concat(ffmpeg_path, [out, out], tmp_path / f"both.{enc.container}", container=enc.container)
    assert ff.count_frames(ffmpeg_path, both) == 24
    png = ff.extract_frame(ffmpeg_path, both, 0.5, tmp_path / "f.png")
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and (tmp_path / "f.png").is_file()
    with pytest.raises(RenderError):
        ff.media_info(ffmpeg_path, tmp_path / "missing.mp4")
