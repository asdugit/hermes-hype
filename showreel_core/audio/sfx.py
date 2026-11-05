"""Cue list -> placed SFX (stdlib only).

Rules (mix doctrine): every sound is aligned on its natural sync point (onset transient, whoosh pass-by
peak, riser end) one frame early; repeats rotate through variants; at most 3 sounds per frame; levels
come from the sound's class (hero -6..0 dB, foley -18..-8 dB) plus the cue's intent gain; at most one
hero impact per film (extra ones become ordinary hits).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Iterable

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "audio"
CLASS_RANGE = {"hero": (-6.0, 0.0), "foley": (-18.0, -8.0)}
HERO_IMPACTS = ("impact", "sub_drop")


@dataclass
class SfxSound:
    name: str
    cls: str
    gain_db: float
    sync: str
    variants: list[dict[str, Any]]
    tags: list[str] = field(default_factory=list)


@dataclass
class PlacedSfx:
    """One SFX instance on the film timeline. ``skip`` trims the head when the sound starts before t=0."""
    name: str
    file: Path
    start: float
    gain_db: float
    cls: str
    cue_t: float
    skip: float = 0.0
    dur: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["file"] = str(self.file)
        return d


@dataclass
class Kit:
    root: Path
    sounds: dict[str, SfxSound]
    styles: dict[str, dict[str, str]]

    def resolve(self, name: str, style: str | None = None) -> SfxSound | None:
        """Sound by name, or by a style role alias (e.g. 'cut' -> 'whoosh_short' in Launch)."""
        if name in self.sounds:
            return self.sounds[name]
        alias = self.styles.get(style or "", {}).get(name) or self.styles.get("launch", {}).get(name)
        return self.sounds.get(alias) if alias else None


def load_kit(assets: Path | None = None) -> Kit | None:
    """Load ``assets/audio/sfx/sfx.json`` (None if the kit is missing)."""
    root = (assets or ASSETS) / "sfx"
    meta = root / "sfx.json"
    if not meta.is_file():
        return None
    data = json.loads(meta.read_text(encoding="utf-8"))
    sounds = {k: SfxSound(k, v["class"], float(v["gain_db"]), v["sync"], v["variants"], v.get("tags", []))
              for k, v in data.get("sounds", {}).items()}
    return Kit(root, sounds, data.get("styles", {}))


def _cue_fields(c: Any) -> tuple[float, str, float, str]:
    if isinstance(c, dict):
        return float(c["t"]), str(c["sfx"]), float(c.get("gain_db", c.get("gain", 0.0))), str(c.get("align", "auto"))
    return float(c.t), str(c.sfx), float(getattr(c, "gain_db", 0.0)), str(getattr(c, "align", "auto"))


def place_cues(cues: Iterable[Any], kit: Kit, duration: float, *, style: str | None = None, fps: float = 30.0,
               lead_frames: float = 1.0, max_per_frame: int = 3) -> tuple[list[PlacedSfx], list[str]]:
    """Turn cues ({t, sfx, gain_db, align}) into placed sounds. Returns (placements, warnings)."""
    warns: list[str] = []
    rr: dict[str, int] = {}
    hero_used = False
    lead = lead_frames / fps
    raw: list[PlacedSfx] = []
    for c in sorted(cues, key=lambda c: _cue_fields(c)[0]):
        t, name, gain, align = _cue_fields(c)
        snd = kit.resolve(name, style)
        if snd is None:
            warns.append(f"unknown sfx '{name}' at {t:.2f}s skipped")
            continue
        if snd.name in HERO_IMPACTS:
            if hero_used:
                alt = kit.resolve("hit", style)
                if alt is None:
                    continue
                warns.append(f"second hero impact at {t:.2f}s replaced by 'hit'")
                snd = alt
            else:
                hero_used = True
        k = rr.get(snd.name, 0)
        rr[snd.name] = k + 1
        var = snd.variants[k % len(snd.variants)]
        point = snd.sync if align in ("auto", "", "None") else align
        if point not in ("onset", "peak", "end"):
            point = snd.sync
        sync_s = float(var.get(point, 0.0))
        lo, hi = CLASS_RANGE.get(snd.cls, (-18.0, 0.0))
        g = max(lo, min(hi, snd.gain_db + gain))
        start = t - sync_s - lead
        skip = 0.0
        if start < 0:
            skip, start = -start, 0.0
        if start >= duration:
            continue
        raw.append(PlacedSfx(snd.name, kit.root / var["file"], round(start, 4), round(g, 2), snd.cls, t, round(skip, 4),
                             float(var.get("dur", 0.0))))
    # at most N sounds whose sync lands in the same frame (heroes first, then louder)
    by_frame: dict[int, list[PlacedSfx]] = {}
    for p in raw:
        by_frame.setdefault(int(p.cue_t * fps), []).append(p)
    kept: list[PlacedSfx] = []
    for _f, group in sorted(by_frame.items()):
        group.sort(key=lambda p: (p.cls != "hero", -p.gain_db))
        if len(group) > max_per_frame:
            warns.append(f"{len(group) - max_per_frame} sfx dropped at {group[0].cue_t:.2f}s (max {max_per_frame}/frame)")
        kept += group[:max_per_frame]
    kept.sort(key=lambda p: p.start)
    return kept, warns


def hero_times(placed: list[PlacedSfx]) -> list[float]:
    """Cue times of hero-class sounds (the music dips under these)."""
    return [p.cue_t for p in placed if p.cls == "hero"]
