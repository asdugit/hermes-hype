"""Earlier films of a session under the plugin's former names, and stills cut out of them, are not product media."""
from __future__ import annotations

from showreel_core.contracts import Event
from showreel_core.pipeline import OWN_TOOLS, _is_derived, derived_pictures, own_output_event


def test_former_plugin_names_are_own_output() -> None:
    assert {"showreel_render", "auteur_render"} <= OWN_TOOLS
    film = Event("a1", 9.0, "artifact", "", "videos/showreel-tempo-5d97-16x9.mp4", "",
                 {"path": "/home/u/.hermes/cache/generated/videos/showreel-tempo-5d97-16x9.mp4"})
    assert own_output_event(film, [], after_first_film=False)
    probe = Event("t1", 10.0, "terminal", "terminal", "F=...", "",
                  {"cmd": "F='~/.hermes/cache/generated/videos/auteur-x-16x9.mp4'; ffprobe \"$F\""})
    assert own_output_event(probe, [], after_first_film=False)


def test_stills_cut_from_an_earlier_film_are_dropped() -> None:
    grab = Event("t2", 11.0, "terminal", "terminal", "F=...", "",
                 {"cmd": "cd ~/scratch/check && F='~/.hermes/cache/generated/videos/showreel-tempo-5d97-16x9.mp4'; "
                         "ffmpeg -y -i \"$F\" -vf \"select='eq(n,315)',tile=2x2\" -frames:v 1 lore-beforeafter.png; "
                         "ls -la lore-beforeafter.png"})
    assert own_output_event(grab, [], after_first_film=True)
    names = derived_pictures([grab])
    assert "lore-beforeafter.png" in names
    look = Event("s1", 12.0, "screenshot", "vision_analyze", "check/lore-beforeafter.png", "",
                 {"src": "~/scratch/check/lore-beforeafter.png", "path": "/jobs/j/assets/e75_lore-beforeafter.png"})
    assert _is_derived(look, names)
    # the product's own screenshots stay
    app = Event("s2", 13.0, "screenshot", "browser", "app/desktop.png", "",
                {"src": "~/app/shots/desktop.png", "path": "/jobs/j/assets/e79_desktop.png"})
    assert not _is_derived(app, names)
    # a command that never read a film marks nothing
    assert derived_pictures([Event("t3", 1.0, "terminal", "terminal", "x", "",
                                   {"cmd": "python shot.py --out desktop.png"})]) == set()
