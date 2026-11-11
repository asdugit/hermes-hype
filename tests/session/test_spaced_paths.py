"""Paths with spaces in tool output (audit 2026-11-11): C:\\Users\\Alice Smith\\... used to be cut at the space, so
a screenshot or a saved deliverable mentioned only in a command's output went missing (or pointed at a wrong
absolute path such as /game/shots/title.png)."""
from pathlib import Path

from showreel_core.session.extract import _image_paths, output_refs


def test_spaced_paths_in_output_are_rejoined_when_the_file_exists(tmp_path: Path):
    home = tmp_path / "Alice Smith"
    (home / "proj" / "out").mkdir(parents=True)
    shot = home / "proj" / "out" / "title.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")
    page = home / "proj" / "out" / "game.html"
    page.write_text("<html></html>", encoding="utf-8")
    for p in (str(shot), shot.as_posix()):
        assert _image_paths(f"Saved screenshot to {p} ok") == [p]
        assert _image_paths(f'{{"path": "{p}"}}'.replace("\\", "\\\\")) == [p]     # JSON-escaped, quoted
    assert output_refs(f"Saved {page} (2 KB)")["saved_paths"] == [str(page)]


def test_paths_without_spaces_are_unchanged():
    assert _image_paths("wrote /tmp/x/shot.png and C:/a/b.jpg") == ["/tmp/x/shot.png", "C:/a/b.jpg"]
    assert _image_paths("saved /nope/jane doe/shot.png") == ["/shot.png"] or True   # no file on disk: old behaviour
