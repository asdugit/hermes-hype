"""9:16 films show the phone capture of a page instead of its desktop capture (ISSUES #52)."""
from showreel_core.contracts import Event, Product, SceneType, Stats, Storyboard, StoryScene
from showreel_core.story.timing import solve_timeline

T = SceneType
URL = "http://127.0.0.1:8765/"


def _cap(i, kind, size, label):
    return Event(f"e{i}", 600.0 + i, "product_capture", "showreel_capture", f"Tempo · {label}", "",
                 {"path": f"cap/{kind}_{i}.png", "url": URL, "kind": kind, "size": size, "label": label,
                  "page_title": "Tempo"}, weight=0.8)


def _timeline(w, h):
    events = [
        Event("e0", 0.0, "user_prompt", "", "", "", {"text": "build a focus timer"}),
        _cap(1, "viewport", [1440, 900], "desktop 1440x900"),
        _cap(2, "element", [976, 1336], "Tasks"),
        _cap(3, "mobile", [780, 1688], "mobile 390x844"),
    ]
    sb = Storyboard(title="Tempo", tagline="A focus timer", cta="Open index.html", mode="product",
                    product=Product(name="Tempo", kind="web_app"), scenes=[
                        StoryScene(T.HOOK, ["e1"], "", "Tempo"),
                        StoryScene(T.TITLE, [], "Meet Tempo, a focus timer for your day.", ""),
                        StoryScene(T.SCREEN, ["e1"], "", "The ring drains as you focus", {"bbox": [0.1, 0.1, 0.5, 0.5]}),
                        StoryScene(T.FEATURE, ["e2"], "", "Tasks you can tick off", {"feature": "Tasks"}),
                        StoryScene(T.END, [], "", ""),
                    ])
    return solve_timeline(sb, events, Stats(duration_s=600), {}, 120.0, 30, "9:16" if h > w else "16:9", 30, w, h, 1)


def _paths(tl):
    out = {}
    for s in tl.scenes:
        img = s.data.get("image") or s.data.get("hero") or {}
        if img.get("path"):
            out[s.type] = img["path"]
    return out


def test_tall_films_use_the_phone_capture():
    tall = _paths(_timeline(1080, 1920))
    assert tall[T.HOOK] == "cap/mobile_3.png" and tall[T.SCREEN] == "cap/mobile_3.png"
    assert tall[T.FEATURE] == "cap/element_2.png"                       # crops keep their own picture
    wide = _paths(_timeline(1920, 1080))
    assert wide[T.HOOK] == wide[T.SCREEN] == "cap/viewport_1.png"


def test_swapped_picture_gets_its_own_focus_box():
    tl = _timeline(1080, 1920)
    screen = next(s for s in tl.scenes if s.type == T.SCREEN)
    assert screen.data["bbox"] != [0.1, 0.1, 0.5, 0.5]                  # the desktop box would point elsewhere
    assert (screen.data["image"]["w"], screen.data["image"]["h"]) == (780, 1688)
