"""Plain data types shared by the Director Engine modules (JSON-able dataclasses)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..contracts import Product


@dataclass
class MediaAsset:
    """One piece of product media the film may use (name = asset key in film.json)."""
    name: str                    # "car"
    type: str                    # "video" | "image"
    path: str                    # absolute source file
    w: int = 0
    h: int = 0
    dur: float = 0.0             # seconds (video)
    fps: float = 0.0
    thumbnail: str = ""          # poster frame (png/jpg) shown to the model
    description: str = ""        # "a glossy red sports car driving left to right"
    product: bool = True         # product media (counts toward product visibility)
    cutout: str = ""             # same media with alpha (video, image or PNG-sequence dir), if available
    frame: str = ""              # "browser" = a web capture (address-bar window ok) | "card" = a picture (game, app,
                                 # render, element crop): shown whole, never in fake browser chrome | "" = unknown

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Capabilities:
    """What the machine/session can do; tells the Director which tools it may plan for."""
    gpu: bool = False
    three: bool = True               # three.js vendored and usable
    vision: bool = True              # the critic model can see images
    image_generate: bool = False     # an image_generate tool is available
    video_generate: bool = False
    blender: bool = False            # Blender is available: `blender:<kit>/<scene>` 3D shots may be used

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Brief:
    """Everything the Director gets for one film."""
    direction: str                                       # the user's words, verbatim
    product: Product | None = None
    digest: str = ""                                     # redacted session digest (may be empty)
    assets: list[MediaAsset] = field(default_factory=list)
    seconds: float = 45.0
    aspect: str = "16:9"
    fps: int = 30
    seed: int = 7
    capabilities: Capabilities = field(default_factory=Capabilities)
    notes: str = ""                                      # extra user notes (revise passes)

    @property
    def size(self) -> tuple[int, int]:
        return (1080, 1920) if self.aspect == "9:16" else (1920, 1080)

    @property
    def preview_size(self) -> tuple[int, int]:
        return (540, 960) if self.aspect == "9:16" else (960, 540)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["product"] = asdict(self.product) if self.product else None
        return d


def brief_from_dict(d: dict[str, Any]) -> Brief:
    """Inverse of :meth:`Brief.to_dict` (tolerant of missing keys)."""
    prod = d.get("product")
    return Brief(
        direction=str(d.get("direction", "")),
        product=Product(**{k: v for k, v in prod.items() if k in Product.__dataclass_fields__}) if prod else None,
        digest=str(d.get("digest", "")),
        assets=[MediaAsset(**{k: v for k, v in a.items() if k in MediaAsset.__dataclass_fields__})
                for a in d.get("assets") or []],
        seconds=float(d.get("seconds", 45.0)), aspect=str(d.get("aspect", "16:9")), fps=int(d.get("fps", 30)),
        seed=int(d.get("seed", 7)),
        capabilities=Capabilities(**{k: v for k, v in (d.get("capabilities") or {}).items()
                                     if k in Capabilities.__dataclass_fields__}),
        notes=str(d.get("notes", "")),
    )


@dataclass(frozen=True)
class Budget:
    """Effort budget: critique rounds, keyframes per shot, repair tries and a hard call cap."""
    rounds: int                 # critique rounds (each critique may be followed by one revision)
    keyframes_per_shot: int
    scene_tries: int            # code attempts per custom scene (first try + repairs) before kit fallback
    film_repairs: int           # extra film/treatment calls when validation fails
    max_calls: int              # hard cap on model calls for the whole run
    max_custom: int = 3         # custom scenes per film
    prominence_repairs: int = 1  # measured-product repair passes per version before the critic looks
    path: str = ""              # force a path ("compose" = engine-assembled from blueprints); "" = by model tier
    deadline_s: float = 0.0     # wall-clock target; late critique/revision steps are skipped to meet it (0 = none)


EFFORTS: dict[str, Budget] = {
    # quick = time-boxed (~10 min with a slow frontier model): kit-first, engine-assembled from blueprints (the model
    # picks + writes words: ~15 s of calls), no custom scene code, one critique and no revision. A real quick job on
    # the free path took 27 min (treatment 4 min + film 9.5 min + custom scene 12 min of model thinking).
    "quick": Budget(rounds=1, keyframes_per_shot=1, scene_tries=2, film_repairs=1, max_calls=16, max_custom=0,
                    path="compose", deadline_s=600.0),
    "standard": Budget(rounds=2, keyframes_per_shot=3, scene_tries=3, film_repairs=2, max_calls=36, max_custom=3,
                       deadline_s=2700.0),
    "max": Budget(rounds=4, keyframes_per_shot=5, scene_tries=4, film_repairs=2, max_calls=72, max_custom=4,
                  prominence_repairs=2),
}
SCORE_BAR = 8.0                 # every rubric score must reach this to stop early
PRODUCT_SHARE_BAR = 0.6         # product visible in >= 60 % of frames (critic-judged)
PRODUCT_HERO_SIZE = 0.25        # product width / frame width that counts as a hero framing
PRODUCT_HERO_BAR = 0.35         # share of keyframes that must frame the product as the hero
RUBRIC_KEYS = ("product_clarity", "composition", "beauty_craft", "story_clarity", "legibility",
               "style_coherence", "transition_quality")


@dataclass
class RoundScore:
    """One critique round: rubric scores and what came of it."""
    round: int
    version: int
    scores: dict[str, float]
    mean: float
    min: float
    product_share: float | None
    passed: bool
    issues: int
    verdict: str = ""
    product_hero: float | None = None     # share of keyframes where the product spans >= PRODUCT_HERO_SIZE of width

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DirectorResult:
    """Outcome of :func:`engine.run` / :func:`engine.revise` (never raised; always returned)."""
    ok: bool
    status: str                                   # "done" | "failed" | "cancelled"
    job_dir: str
    film: dict[str, Any] | None = None
    film_path: str = ""
    page_dir: str = ""                            # built + dry-run-verified page (render this)
    scene_files: dict[str, str] = field(default_factory=dict)   # custom scene id -> final JS file
    treatment: dict[str, Any] | None = None
    version: int = 0                              # the version that became film.json
    scores: list[RoundScore] = field(default_factory=list)
    passed_bar: bool = False
    scenes: dict[str, str] = field(default_factory=dict)   # custom scene -> "ok" | "fallback:<kit scene>"
    library_saved: list[str] = field(default_factory=list)
    fallback: str = ""                            # "quick" when the caller should fall back to Quick mode
    quick_style: str = ""
    error: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    seconds: float = 0.0
    log: list[dict[str, Any]] = field(default_factory=list)
    measured: dict[str, Any] = field(default_factory=dict)        # pixel-measured product prominence of the result
    narration: list[dict[str, Any]] = field(default_factory=list)  # [{path, start, duration, text, speed}]
    tier: dict[str, Any] = field(default_factory=dict)             # model tier + path used (free/compose/floor)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scores"] = [s.to_dict() for s in self.scores]
        return d
