"""Asset collection: copies, missing originals, inline images, header-based image sizes, caps."""
import base64
import struct
import zlib

from session_synth import Transcript

from showreel_core.session import collect_assets, extract_events
from showreel_core.session.assets import image_size, resolve_local


def tiny_png(w=3, h=2):
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_image_size_headers():
    assert image_size(tiny_png(7, 5)) == (7, 5)
    assert image_size(b"GIF89a" + struct.pack("<HH", 10, 20)) == (10, 20)
    jpeg = b"\xff\xd8" + b"\xff\xe0" + struct.pack(">H", 4) + b"JF" + b"\xff\xc0" + struct.pack(">HBHH", 11, 8, 33, 44) + b"\x00" * 8
    assert image_size(jpeg) == (44, 33)
    vp8x = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"VP8X" + b"\x00" * 8 + (99).to_bytes(3, "little") + (49).to_bytes(3, "little")
    assert image_size(vp8x) == (100, 50)
    assert image_size(b"not an image") == (None, None)


def test_collect_copies_existing_marks_missing_writes_inline(tmp_path):
    src = tmp_path / "shots dir" / "ünï shot.png"
    src.parent.mkdir()
    src.write_bytes(tiny_png(4, 3))
    inline = base64.b64encode(tiny_png(2, 2)).decode()
    t = Transcript().user("go")
    t.call("vision_analyze", {"image_url": str(src), "question": "ok?"}, "Image loaded")
    t.call("vision_analyze", {"image_url": str(src), "question": "again?"}, "Image loaded")
    t.call("vision_analyze", {"image_url": str(tmp_path / "gone.png"), "question": "?"}, "Image loaded")
    t.call("computer_use", {"action": "capture"},
           [{"type": "text", "text": "capture"}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{inline}"}}])
    events = extract_events(t.rows).events
    out = tmp_path / "job" / "assets"
    rep = collect_assets(events, out)
    shots = [e for e in events if e.kind == "screenshot"]
    assert rep.copied == 1 and rep.reused == 1 and rep.missing == 1 and rep.inline == 1
    first, second, gone, inl = shots
    assert first.data["asset"] and first.data["path"].startswith(str(out.resolve())) and (first.data["w"], first.data["h"]) == (4, 3)
    assert second.data["path"] == first.data["path"]
    assert gone.data["missing"] and gone.data["path"] == "" and gone.weight < first.weight
    assert inl.data["path"].endswith(".png") and "_inline_b64" not in inl.data and inl.data["w"] == 2


def test_collect_without_dir_drops_inline_payloads_and_respects_cap(tmp_path):
    files = []
    for i in range(3):
        p = tmp_path / f"s{i}.png"
        p.write_bytes(tiny_png())
        files.append(p)
    t = Transcript().user("go")
    for p in files:
        t.call("vision_analyze", {"image_url": str(p), "question": "?"}, "Image loaded")
    events = extract_events(t.rows).events
    rep = collect_assets(events, tmp_path / "a", max_files=2)
    assert rep.copied == 2 and rep.skipped == 1
    events2 = extract_events(t.rows).events
    rep2 = collect_assets(events2, None)
    assert rep2.copied == 0 and all(e.data.get("path", "") == "" for e in events2 if e.kind == "screenshot")


def test_resolve_local_forms(tmp_path):
    assert resolve_local("relative.png") is None
    assert resolve_local("relative.png", tmp_path) == tmp_path / "relative.png"
    assert resolve_local(f"file://{tmp_path.as_posix()}/x.png") is not None
    assert resolve_local("") is None
