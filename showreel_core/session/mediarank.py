"""Rank a session's pictures and set aside its debug artefacts (contact sheets, B&W tests, probes, near-duplicates).

A long build session leaves dozens of working images behind: grids of character heads, black-and-white
lighting tests, depth/normal passes, numbered retries of the same render. A film made of those reads as a
debug log, so before the storyboard sees the pictures every visual event gets ``data["media_rank"]``::

    {"score": 0..1, "junk": bool, "why": ["token:sheet", "grid", ...], "hash": "16 hex"}

Junk pictures are never shown (``story.facts.image_of`` ignores them) and lose most of their weight, so the
digest, the capture planner and the heuristic storyboard all pick the real product shots first.

Signals (Pillow only, on a <= 160 px thumbnail; a missing file falls back to the name and pixel size):
- file-name tokens of working files (sheet, contact, grid, heads, debug, test, tmp, bw, flicker, probe, mask,
  wire, uv, depth, normal, ``zf_`` ...) and numbered retries of one base name (keep the newest);
- a contact sheet / grid: several evenly spaced full-length seams or uniform gutters;
- a near-greyscale picture when the session's other pictures are colourful;
- tiny pictures and extreme strips (aspect > 2.6 or < 0.38);
- near-identical frames (64-bit difference hash, Hamming distance <= 5): only the best one stays;
- bonus: pictures the assistant presented (MEDIA: lines, delivered artefacts, product shots, named in the
  final answer) and hero-ish names (final, hero, screenshot, gameplay, ingame, title, menu, poster).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from ..contracts import Event

#: event kinds that carry a picture
VISUAL_KINDS = ("product_capture", "screenshot", "image_generated", "artifact")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

#: file-name tokens of working/debug pictures (matched against the tokenised stem)
DEBUG_TOKENS = frozenset({
    "sheet", "sheets", "contact", "contacts", "grid", "grids", "heads", "head", "debug", "dbg", "test", "tests",
    "tmp", "temp", "bw", "flicker", "probe", "probes", "mask", "masks", "wire", "wireframe", "uv", "uvs", "depth",
    "normal", "normals", "zf", "diag", "variants", "montage", "tiles", "atlas", "matte", "alpha", "ao",
    "compare", "comparison", "pair", "pairs", "strip", "swatch", "swatches", "palette", "histogram", "gizmo",
})
#: tokens of pictures meant to be seen
HERO_TOKENS = frozenset({
    "final", "hero", "screenshot", "screen", "gameplay", "ingame", "title", "menu", "poster", "cover", "keyart",
    "trailer", "showcase", "promo", "beauty", "launch", "release", "lobby", "scene", "shot",
})
#: compiled once: leading asset prefix "e123_" (session/assets.py names copies like that)
_ASSET_PREFIX = re.compile(r"^e\d+_")
_SPLIT = re.compile(r"[^a-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
#: numbered retries: "owen2", "owen_v3", "sign-2", "flicker_bw_a" -> base
_RETRY_TAIL = re.compile(r"(?:[_\-. ]?v?\d{1,3}|[_\-][a-z])$")

EXTREME_ASPECT = (0.38, 2.6)
TINY_SIDE = 200
TINY_AREA = 160_000
DUP_BITS = 5


def tokens(name: str) -> list[str]:
    """Lower-case word tokens of a file name (no extension, no ``e123_`` asset prefix; digits split off)."""
    stem = Path(str(name or "")).stem
    stem = _ASSET_PREFIX.sub("", stem)
    stem = _CAMEL.sub("_", stem).lower()
    out: list[str] = []
    for part in _SPLIT.split(stem):
        if not part:
            continue
        m = re.match(r"^([a-z]+)(\d+)$", part)
        if m:
            out += [m.group(1), m.group(2)]
        else:
            out.append(part)
    return out


def retry_base(name: str) -> str:
    """The base name of a numbered retry (``g_heads_owen3`` -> ``g_heads_owen``); '' when there is no tail."""
    stem = _ASSET_PREFIX.sub("", Path(str(name or "")).stem.lower())
    base = stem
    for _ in range(2):
        nb = _RETRY_TAIL.sub("", base)
        if nb == base or len(nb) < 3:
            break
        base = nb
    return base if base != stem else ""


def name_signals(name: str) -> tuple[list[str], float]:
    """(debug reasons, name bonus) from a file name alone."""
    toks = tokens(name)
    why = [f"token:{t}" for t in toks if t in DEBUG_TOKENS]
    bonus = 0.12 if any(t in HERO_TOKENS for t in toks) else 0.0
    return sorted(set(why)), bonus


# ------------------------------------------------------------------------------------------- pixels

def _axis_profile(px: list[int], w: int, h: int, axis: str) -> tuple[list[float], list[float], list[bool]]:
    """Per position on one axis: (ratio, share, gutter).

    ratio = mean brightness step across the position / the median step of its neighbourhood (a seam between two
    butted pictures spikes); share = the fraction of crossing lines on which that step is the strongest one
    nearby (an object edge covers part of the picture, a seam all of it); gutter = a uniform line (separator
    band) in an otherwise busy picture."""
    n, m = (w, h) if axis == "x" else (h, w)
    rows = [px[j * w:(j + 1) * w] for j in range(h)] if axis == "x" else [px[j::w] for j in range(w)]
    share = [0] * n
    diff = [0.0] * n
    for r in rows:
        g = [0] * n
        for i in range(1, n - 1):
            g[i] = abs(r[i + 1] - r[i - 1])
            diff[i] += g[i]
        for i in range(2, n - 2):
            gi = g[i]
            if gi >= 8 and gi >= max(g[max(1, i - 4):i + 5]):
                share[i] += 1
    diff = [d / m for d in diff]
    spread = []
    for i in range(n):
        vals = [r[i] for r in rows]
        mu = sum(vals) / m
        spread.append((sum((v - mu) ** 2 for v in vals) / m) ** 0.5)
    busy = sorted(spread)[n // 2]
    ratio, sh, gut = [0.0] * n, [0.0] * n, [False] * n
    for i in range(2, n - 2):
        ring = [diff[k] for k in range(max(1, i - 10), min(n - 1, i + 11)) if abs(k - i) > 2]
        base = sorted(ring)[len(ring) // 2] if ring else 0.0
        ratio[i] = diff[i] / (base + 1.5)
        sh[i] = max(share[i], share[i] + max(share[i - 1], share[i + 1]) // 2) / m   # resampling smears a seam
        gut[i] = busy > 15 and spread[i] < 4.0
    return ratio, sh, gut


#: seam grades: (min share, min ratio)
STRONG = (0.5, 2.0)
MODERATE = (0.34, 1.8)


def tiles(prof: tuple[list[float], list[float], list[bool]], n: int, grade: tuple[float, float],
          ks: Iterable[int] = range(2, 9)) -> int:
    """Smallest k whose k-1 interior tile lines (j * n / k, +-2.5 %) are all seams of ``grade`` (or gutters);
    0 for none."""
    ratio, share, gut = prof
    tol = max(2, int(0.025 * n))
    for k in ks:
        ok = True
        for j in range(1, k):
            c = round(j * n / k)
            if not any(gut[i] or (share[i] >= grade[0] and ratio[i] >= grade[1])
                       for i in range(max(2, c - tol), min(n - 2, c + tol + 1))):
                ok = False
                break
        if ok:
            return k
    return 0


def is_grid(px: list[int], w: int, h: int) -> bool:
    """A contact sheet / tile grid: pictures butted together (or separated by gutters) on an even grid.

    Any axis cut into >= 3 equal tiles by strong seams; tile lines on both axes (moderate seams); or two
    pictures side by side (one strong vertical seam in the middle) or stacked (a very strong horizontal one: a
    horizon line can sit in the middle of a real shot)."""
    if w < 24 or h < 24:
        return False
    px_ = _axis_profile(px, w, h, "x")
    py_ = _axis_profile(px, w, h, "y")
    if tiles(px_, w, STRONG, range(3, 9)) or tiles(py_, h, STRONG, range(3, 9)):
        return True
    if tiles(px_, w, MODERATE) and tiles(py_, h, MODERATE):
        return True
    return bool(tiles(px_, w, STRONG, (2,)) or tiles(py_, h, (0.6, 2.0), (2,)))


def _pixels(im: Any) -> list[Any]:
    """Flat pixel list (Pillow >= 12 has get_flattened_data; getdata is deprecated there)."""
    f = getattr(im, "get_flattened_data", None)
    return list(f() if f is not None else im.getdata())


def dhash(gray9x8: list[int]) -> int:
    """64-bit difference hash of a 9x8 grey thumbnail."""
    v = 0
    for y in range(8):
        for x in range(8):
            v = (v << 1) | (1 if gray9x8[y * 9 + x] > gray9x8[y * 9 + x + 1] else 0)
    return v


def analyze_pixels(path: str | Path) -> dict[str, Any] | None:
    """Pixel facts of one picture: {w, h, sat (mean HSV saturation 0..1), colorful (Hasler-Suesstrunk, ~0..1),
    detail (edge density 0..1), grid (bool), hash (int)}; None when unreadable."""
    try:
        from PIL import Image, ImageFilter  # lazy: Pillow is a Hermes core dependency
        with Image.open(path) as im:
            im.seek(0)
            w0, h0 = im.size
            rgb = im.convert("RGB")
        th = rgb.copy()
        th.thumbnail((160, 160))
        hsv = th.convert("HSV")
        sats = _pixels(hsv.getchannel("S"))
        sat = sum(sats) / (255.0 * max(1, len(sats)))
        rr, gg, bb = (_pixels(c) for c in th.split())
        rg = [a - b for a, b in zip(rr, gg)]
        yb = [(a + b) / 2 - c for a, b, c in zip(rr, gg, bb)]

        def ms(v: list[float]) -> tuple[float, float]:
            m = sum(v) / max(1, len(v))
            return m, (sum((x - m) ** 2 for x in v) / max(1, len(v))) ** 0.5

        (mrg, srg), (myb, syb) = ms(rg), ms(yb)
        colorful = ((srg ** 2 + syb ** 2) ** 0.5 + 0.3 * (mrg ** 2 + myb ** 2) ** 0.5) / 110.0
        gray = th.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        ev = _pixels(edges)
        detail = sum(1 for x in ev if x > 40) / max(1, len(ev))
        g2 = rgb.convert("L")
        g2.thumbnail((200, 200))
        gw, gh = g2.size
        grid = is_grid(_pixels(g2), gw, gh)
        h9 = _pixels(rgb.convert("L").resize((9, 8)))
        return {"w": w0, "h": h0, "sat": round(sat, 4), "colorful": round(min(1.5, colorful), 4),
                "detail": round(detail, 4), "grid": grid, "hash": dhash(h9)}
    except Exception:  # noqa: BLE001 - unreadable/missing picture: name-only ranking
        return None


# ------------------------------------------------------------------------------------------- events

def picture_path(ev: Event) -> str:
    """The local picture file of a visual event ('' when there is none)."""
    d = ev.data or {}
    if ev.kind == "artifact":
        p = str(d.get("preview_path") or "")
        if not p and (str(d.get("path", "")).lower().endswith(IMAGE_EXTS) or d.get("kind") == "image"):
            p = str(d.get("path") or "")
        return p
    return str(d.get("path") or "")


def _is_web_shot(ev: Event) -> bool:
    """A capture of a real page (url/html/pdf target; older captures without target_kind: an http(s) page)."""
    d = ev.data or {}
    if ev.kind != "product_capture":
        return False
    tk = str(d.get("target_kind") or "")
    if tk:
        return tk in ("url", "html", "pdf")
    url = str(d.get("url") or "").lower()
    return url.startswith(("http://", "https://", "file://")) and d.get("kind") not in ("image", "video") \
        and not url.split("?")[0].endswith(IMAGE_EXTS)


def _presented(ev: Event, final_text: str) -> bool:
    d = ev.data or {}
    if d.get("delivered") or d.get("artifact") or d.get("product_shot") or d.get("source") == "deliverable":
        return True
    name = Path(picture_path(ev) or str(d.get("src") or "")).name
    stem = _ASSET_PREFIX.sub("", name)
    return bool(stem) and len(stem) > 6 and stem in final_text


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def rank_media(events: list[Event], *, analyze: bool = True) -> dict[str, Any]:
    """Score every picture event in place (``data["media_rank"]``, weight) and return a summary
    ``{"pictures": n, "junk": n, "kept": [ids best first]}``. Never raises; web captures are never junked."""
    final_text = " ".join(str((e.data or {}).get("text") or "") for e in events if e.kind == "final_answer")
    rows: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any] | None] = {}
    for ev in events:
        if ev.kind not in VISUAL_KINDS:
            continue
        d = ev.data or {}
        path = picture_path(ev)
        if ev.kind == "artifact" and not path:
            continue
        if d.get("kind") == "video" or d.get("stub"):
            continue
        key = str(d.get("src_key") or d.get("src") or path or ev.id)
        if analyze and path and path not in cache:
            cache[path] = analyze_pixels(path)
        px = cache.get(path) if analyze and path else None
        name = Path(path or str(d.get("src") or d.get("page_title") or "")).name
        if ev.kind == "product_capture" and d.get("page_title") and not _is_web_shot(ev):
            name = str(d.get("page_title"))          # a captured file keeps its own name ("g_heads_owen5.jpg")
        rows.append({"ev": ev, "path": path, "px": px, "name": name, "key": key, "web": _is_web_shot(ev)})
    if not rows:
        return {"pictures": 0, "junk": 0, "kept": []}
    colourful_set = sorted(r["px"]["colorful"] for r in rows if r["px"])
    set_colour = colourful_set[len(colourful_set) // 2] if colourful_set else 0.0
    for r in rows:
        ev, px = r["ev"], r["px"]
        d = ev.data or {}
        why, bonus = ([], 0.0) if r["web"] else name_signals(r["name"])
        w = (px or {}).get("w") or d.get("w") or ((d.get("size") or [None, None])[0])
        h = (px or {}).get("h") or d.get("h") or ((d.get("size") or [None, None])[1])
        score = 0.5 + bonus
        if not r["web"]:
            try:
                w, h = int(w or 0), int(h or 0)
            except (TypeError, ValueError):
                w = h = 0
            if w and h:
                a = w / h
                if a > EXTREME_ASPECT[1] or a < EXTREME_ASPECT[0]:
                    why.append(f"aspect:{a:.2f}")
                if min(w, h) < TINY_SIDE or w * h < TINY_AREA:
                    why.append("tiny")
            if px:
                if px["grid"]:
                    why.append("grid")
                if px["sat"] < 0.06 and px["colorful"] < 0.08 and set_colour >= 0.18:
                    why.append("greyscale")
        if px:
            score += 0.25 * min(1.0, px["detail"] / 0.25) + 0.15 * min(1.0, px["colorful"] / 0.5)
        if _presented(ev, final_text):
            score += 0.15
            r["presented"] = True
        r["score"] = round(min(1.0, score), 4)
        r["why"] = why
    # numbered retries of one base name: keep the newest
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        b = "" if r["web"] else retry_base(r["name"])
        if b:
            groups.setdefault(b, []).append(r)
    for b, grp in groups.items():
        if len(grp) < 2:
            continue
        newest = max(grp, key=lambda q: (q["ev"].t, q["ev"].id))
        for q in grp:
            if q is not newest and q["key"] != newest["key"]:
                q["why"].append(f"retry:{b}")
    # near-identical frames: keep the best of each cluster (different events of one file are not duplicates)
    hashed = sorted((r for r in rows if r["px"] and not r["why"]), key=lambda q: (-q["score"], -q["ev"].t))
    kept_h: list[dict[str, Any]] = []
    for r in hashed:
        dup = next((k for k in kept_h if k["key"] != r["key"]
                    and _hamming(k["px"]["hash"], r["px"]["hash"]) <= DUP_BITS), None)
        if dup is not None and not r["web"]:
            r["why"].append(f"duplicate:{dup['ev'].id}")
        else:
            kept_h.append(r)
    n_junk = 0
    for r in rows:
        ev = r["ev"]
        junk = bool(r["why"]) and not r["web"]
        n_junk += junk
        info = {"score": r["score"], "junk": junk, "why": r["why"][:6]}
        if r["px"]:
            info["hash"] = f"{r['px']['hash']:016x}"
            info["sat"], info["detail"] = r["px"]["sat"], r["px"]["detail"]
        if r.get("presented"):
            info["presented"] = True
        ev.data["media_rank"] = info
        if junk:
            ev.weight = round(min(ev.weight, 0.05), 3)
        else:
            ev.weight = round(min(1.0, ev.weight * (0.75 + 0.5 * r["score"])), 3)
    kept = [r["ev"].id for r in sorted(rows, key=lambda q: (-q["score"], -q["ev"].t))
            if r["path"] and not (r["ev"].data.get("media_rank") or {}).get("junk")]
    return {"pictures": len(rows), "junk": n_junk, "kept": kept}


def is_junk(ev: Event | None) -> bool:
    """True when the ranking set this picture aside as a working/debug artefact."""
    return bool(ev is not None and ((ev.data or {}).get("media_rank") or {}).get("junk"))


def media_score(ev: Event | None) -> float:
    """The ranking score (0.5 when unranked)."""
    if ev is None:
        return 0.0
    return float(((ev.data or {}).get("media_rank") or {}).get("score", 0.5))


def propagate(events: Iterable[Event]) -> None:
    """Captured copies of session pictures (``product_capture`` with ``source_ids``) inherit their source's
    junk verdict, so a contact sheet re-captured by the capture stage stays out too."""
    evs = list(events)
    by_id = {e.id: e for e in evs}
    for ev in evs:
        if ev.kind != "product_capture" or _is_web_shot(ev):
            continue
        srcs = [by_id.get(i) for i in (ev.data or {}).get("source_ids") or []]
        bad = [s for s in srcs if is_junk(s)]
        if bad:
            mr = dict((ev.data or {}).get("media_rank") or {"score": 0.3})
            mr["junk"] = True
            mr["why"] = list(mr.get("why") or []) + [f"source:{bad[0].id}"]
            ev.data["media_rank"] = mr
            ev.weight = round(min(ev.weight, 0.05), 3)
