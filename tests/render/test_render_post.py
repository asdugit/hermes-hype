"""Post-chain graph construction (pure) plus a real ffmpeg run of every chain on tiny frames."""
from __future__ import annotations

import io
import re
import subprocess

import pytest

from showreel_core.render import ffmpeg as ff
from showreel_core.render import post
from showreel_core.render.errors import RenderError

PALETTE = ["#0f0f1b", "#565a75", "#c6b7be", "#fafbf6", "#ff6b97", "#8ae1ff"]


def _labels_ok(graph: str) -> None:
    """Every [sN] label is produced exactly once and consumed exactly once; output is [vout]."""
    produced: list[str] = []
    consumed: list[str] = []
    for part in graph.split(";"):
        ins = re.match(r"^((?:\[[^\]]+\])+)", part)
        outs = re.search(r"((?:\[[^\]]+\])+)$", part)
        assert ins and outs, part
        consumed += re.findall(r"\[([^\]]+)\]", ins.group(1))
        produced += re.findall(r"\[([^\]]+)\]", outs.group(1))
    internal = [p for p in produced if p != "vout"]
    assert sorted(internal) == sorted(c for c in consumed if not c.endswith(":v"))
    assert produced.count("vout") == 1 and graph.endswith("[vout]")


def test_parse_spec():
    assert post.parse_spec(None) == [] and post.parse_spec("none") == []
    assert post.parse_spec("bloom+grain_vignette+bloom") == ["bloom", "grain_vignette"]
    with pytest.raises(RenderError):
        post.parse_spec("bloom+sparkles")


def test_none_chain_is_explicit_colour_conversion():
    pc = post.build_post("none", in_size=(1920, 1080), out_size=(1920, 1080))
    assert pc.graph.startswith("[0:v]scale=in_range=pc:in_color_matrix=bt601,format=gbrp")
    assert "out_color_matrix=bt709" in pc.graph and "format=yuv420p" in pc.graph
    assert "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709" in pc.graph
    assert pc.extra_inputs == ()
    _labels_ok(pc.graph)


def test_resize_uses_lanczos_unless_pixel():
    pc = post.build_post("none", in_size=(960, 540), out_size=(1920, 1080))
    assert "scale=1920:1080:flags=lanczos" in pc.graph


@pytest.mark.parametrize("spec", ["grain_vignette", "crt", "bloom", "pixel", "bloom+grain_vignette", "pixel+crt"])
def test_graphs_are_well_formed(spec, tmp_path):
    params = {"pixel": {"palette": PALETTE}}
    insz = (480, 270) if "pixel" in spec else (1920, 1080)
    pc = post.build_post(spec, in_size=insz, out_size=(1920, 1080), seed=7, params=params, work_dir=tmp_path)
    _labels_ok(pc.graph)
    n_inputs = pc.extra_inputs.count("-i")
    for k in range(1, n_inputs + 1):
        assert f"[{k}:v]" in pc.graph
    for name in post.parse_spec(spec):
        assert set(post.REQUIRED_FILTERS[name]) <= set(pc.required_filters)


def test_pixel_palette_and_nearest_upscale(tmp_path):
    pc = post.build_post("pixel", in_size=(270, 480), out_size=(1080, 1920), params={"pixel": {"palette": PALETTE}},
                         work_dir=tmp_path)
    assert "paletteuse=dither=none" in pc.graph and "scale=1080:1920:flags=neighbor" in pc.graph
    assert pc.graph.index("paletteuse") < pc.graph.index("flags=neighbor")  # quantise before upscaling
    from PIL import Image
    pal = Image.open(tmp_path / "palette.png")
    assert pal.size == (16, 16)
    rgb = pal.convert("RGB")
    assert rgb.getpixel((0, 0)) == (0x0F, 0x0F, 0x1B) and rgb.getpixel((15, 15)) == (0x8A, 0xE1, 0xFF)  # padded


def test_pixel_without_palette_needs_no_inputs():
    pc = post.build_post("pixel", in_size=(480, 270), out_size=(1920, 1080))
    assert pc.extra_inputs == () and "paletteuse" not in pc.graph


def test_mask_chains_need_work_dir():
    with pytest.raises(RenderError):
        post.build_post("crt", in_size=(64, 36), out_size=(64, 36))


def test_crt_mask_has_scanlines_and_vignette(tmp_path):
    pc = post.build_post("crt", in_size=(1920, 1080), out_size=(1920, 1080), work_dir=tmp_path)
    assert "loop=loop=-1:size=1:start=0" in pc.graph and "blend=all_mode=multiply:shortest=1" in pc.graph
    assert "lenscorrection" in pc.graph
    from PIL import Image
    mask = Image.open(next(tmp_path.glob("mask_*.png"))).convert("L")
    px = lambda x, y: int(mask.getpixel((x, y)))
    assert mask.size == (1920, 1080)
    cx = 960
    light, dark = 540, 542                       # period 3: rows with y % 3 == 2 are darkened
    assert px(cx, light) > px(cx, dark)
    assert px(cx, light) > px(5, light)  # vignette


def test_grain_seed_is_deterministic_and_per_chunk(tmp_path):
    a = post.chain_seed(1234, 0)
    assert a == post.chain_seed(1234, 0) and a != post.chain_seed(1234, 1) and 0 <= a < 2 ** 31
    pc = post.build_post("grain_vignette", in_size=(64, 36), out_size=(64, 36), seed=a, work_dir=tmp_path)
    assert f"c0_seed={a}" in pc.graph


def test_bad_palette_colour(tmp_path):
    with pytest.raises(RenderError):
        post.write_palette_png(["#12345"], tmp_path / "p.png")


@pytest.mark.parametrize("spec", ["none", "grain_vignette", "crt", "bloom", "pixel", "bloom+grain_vignette"])
def test_chains_run_in_ffmpeg(spec, ffmpeg_path, tmp_path):
    from PIL import Image

    caps = ff.capabilities(ffmpeg_path)
    missing = [f for n in ["none", *post.parse_spec(spec)] for f in post.REQUIRED_FILTERS[n] if f not in caps.filters]
    if missing:
        pytest.skip(f"ffmpeg lacks {missing}")
    insz = (80, 45) if "pixel" in spec else (320, 180)
    frames = []
    for i in range(6):
        b = io.BytesIO()
        Image.new("RGB", insz, (40 * i, 120, 250 - 30 * i)).save(b, "JPEG", quality=92)
        frames.append(b.getvalue())
    pc = post.build_post(spec, in_size=insz, out_size=(320, 180), seed=3, params={"pixel": {"palette": PALETTE}},
                         work_dir=tmp_path)
    enc = ff.encoder_spec(ff.pick_encoder(caps), 320, 180, 30)
    out = tmp_path / f"o.{enc.container}"
    cmd = ff.chunk_encode_cmd(ffmpeg_path, fps=30, out_path=out, enc=enc, filter_graph=pc.graph,
                              extra_inputs=pc.extra_inputs)
    p = subprocess.run(cmd, input=b"".join(frames), capture_output=True, timeout=60, check=False)
    assert p.returncode == 0, p.stderr.decode()[-600:]
    assert ff.parse_progress(p.stdout.decode())["frame"] == "6"
    assert "bt709" in ff.media_info(ffmpeg_path, out).color and "unknown" not in ff.media_info(ffmpeg_path, out).color
