"""Read models for the Auteur Desktop pane (stdlib + optional Pillow; no FastAPI, no core imports).

``plugin_api.py`` loads this file by path and calls these functions from the thread pool. Everything
here reads files a job or the Director already wrote: job records, ``<job>/director/`` artefacts
(``log.jsonl``, ``treatment.json``, ``v<N>/{film,critique,changes}.json``, ``v<N>/scenes/*.js``,
``v<N>/contact-*.jpg``, ``calls/*.meta.json``), the user's scene library and the shipped style
previews. Nothing here writes, and nothing raises on a missing or half-written file: readers get
empty values instead, because the runner may be replacing a file at the moment the pane polls.
"""
from __future__ import annotations

import base64
import io
import json
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

#: Gallery order (the user's roster, Nov 6): kept first, every other discovered style after it.
ROSTER = ("launch", "cinematic", "pixel", "terminal", "blueprint", "comic", "ink", "nature")
IMAGE_MIME = {".webp": "image/webp", ".gif": "image/gif", ".png": "image/png", ".jpg": "image/jpeg",
              ".jpeg": "image/jpeg"}
VIDEO_MIME = {".mp4": "video/mp4", ".webm": "video/webm"}
PREVIEW_EXTS = (".webp", ".gif", ".png", ".jpg", ".jpeg", ".mp4", ".webm")
PREVIEW_INLINE = 120 * 1024        # previews this small ride along in GET /styles
PREVIEW_IMAGE_LIMIT = 900 * 1024   # GET /styles/{id}/preview caps (a 3-4 s 320x180 loop is ~150-400 KB)
PREVIEW_VIDEO_LIMIT = 2 * 1024 * 1024
LIBRARY_THUMB_LIMIT = 300 * 1024
MSG_CAP = 900                      # characters of one Director log message sent to the pane
RUBRIC = ("product_clarity", "composition", "beauty_craft", "story_clarity", "legibility", "style_coherence",
          "transition_quality")
TERMINAL_STAGES = frozenset({"done", "failed", "cancelled"})
_CODING = re.compile(r"^Coding scene\s+[`'\"]?([\w.-]+)", re.I)
_SHEET_NAME = re.compile(r"^contact-\d{1,3}\.jpg$")
_KEYFRAME_NAME = re.compile(r"^\d{2,3}-[\w.-]{1,80}\.png$")
_VERSION_DIR = re.compile(r"^v(\d{1,3})$")
_SCENE_NAME = re.compile(r"^[\w.-]{1,80}$")


# ----------------------------------------------------------------------------------- small utils

def read_json(path: Path) -> Any:
    """Parsed JSON, or ``None`` when the file is missing, unreadable or mid-write."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def mime_of(path: Path) -> str:
    """MIME type of a preview/thumbnail file by suffix ('' for anything else)."""
    ext = path.suffix.lower()
    return IMAGE_MIME.get(ext) or VIDEO_MIME.get(ext) or ""


def data_url(path: Path | str, limit: int) -> str:
    """``data:`` URL of a small image/video file, or '' (missing, unknown type, larger than ``limit``)."""
    p = Path(path)
    mime = mime_of(p)
    try:
        if not mime or not p.is_file() or p.stat().st_size > limit:
            return ""
        return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")
    except OSError:
        return ""


def inside(base: Path, candidate: Path) -> Path | None:
    """``candidate`` resolved, when it lies inside ``base`` (symlinks and ``..`` resolved), else ``None``."""
    try:
        root = base.resolve()
        path = candidate.resolve()
    except OSError:
        return None
    return path if path == root or root in path.parents else None


def clip(text: Any, limit: int) -> str:
    """``text`` as a string of at most ``limit`` characters (an ellipsis marks a cut)."""
    s = str(text or "")
    return s if len(s) <= limit else s[: max(0, limit - 1)].rstrip() + "…"


# ----------------------------------------------------------------------------------- style previews

def find_preview(style_id: str, declared: str, roots: list[Path]) -> Path | None:
    """The style's preview file: the one its kit/pack declares, else ``<root>/<id>.<ext>`` in ``roots``."""
    if declared:
        p = Path(declared)
        if p.is_file() and p.suffix.lower() in PREVIEW_EXTS:
            return p
    for root in roots:
        for ext in PREVIEW_EXTS:
            p = root / f"{style_id}{ext}"
            if p.is_file():
                return p
    return None


def style_rows(styles: list[dict[str, Any]], roots: list[Path]) -> list[dict[str, Any]]:
    """Gallery rows in roster order: meta + preview availability (small previews inline as data URLs).

    ``styles`` are ``StyleInfo.to_dict()`` rows (their ``preview`` is an absolute path or '').
    """
    out = []
    for s in styles:
        sid = str(s.get("id") or "")
        if not sid:
            continue
        found = find_preview(sid, str(s.get("preview") or ""), roots)
        kind = "video" if found is not None and found.suffix.lower() in VIDEO_MIME else "image" if found else ""
        row = {k: v for k, v in s.items() if k != "preview"}
        row.update(has_preview=found is not None, preview_kind=kind,
                   preview_url=data_url(found, PREVIEW_INLINE) if found is not None and kind == "image" else "")
        out.append(row)
    rank = {sid: k for k, sid in enumerate(ROSTER)}
    return sorted(out, key=lambda r: (rank.get(r["id"], len(ROSTER)), r["id"]))


def preview_payload(style_id: str, declared: str, roots: list[Path]) -> dict[str, Any] | None:
    """``{id, kind, mime, url}`` for one style's preview (``url`` '' when the file is too large), or None."""
    found = find_preview(style_id, declared, roots)
    if found is None:
        return None
    video = found.suffix.lower() in VIDEO_MIME
    url = data_url(found, PREVIEW_VIDEO_LIMIT if video else PREVIEW_IMAGE_LIMIT)
    return {"id": style_id, "kind": "video" if video else "image", "mime": mime_of(found), "url": url,
            "bytes": found.stat().st_size if found.is_file() else 0}


# ----------------------------------------------------------------------------------- job records

class JobCache:
    """``job.json`` reads keyed by (mtime, size): the status chip and job lists poll every few seconds,
    and a job record carries up to 400 log lines, so unchanged files are not parsed again."""

    def __init__(self, cap: int = 256) -> None:
        self._cap = cap
        self._items: OrderedDict[str, tuple[int, int, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def load(self, path: Path) -> dict[str, Any] | None:
        try:
            st = path.stat()
        except OSError:
            return None
        key = str(path)
        with self._lock:
            hit = self._items.get(key)
            if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
                self._items.move_to_end(key)
                return hit[2]
        data = read_json(path)
        if not isinstance(data, dict):
            return None
        with self._lock:
            self._items[key] = (st.st_mtime_ns, st.st_size, data)
            while len(self._items) > self._cap:
                self._items.popitem(last=False)
        return data

    def jobs(self, jobs_dir: Path, valid: Any, session_id: str | None = None, limit: int = 50,
             ) -> list[dict[str, Any]]:
        """Job records newest first (``valid`` is ``jobs.valid_id``), optionally one session's only."""
        if not jobs_dir.is_dir():
            return []
        found = []
        for d in jobs_dir.iterdir():
            if not valid(d.name):
                continue
            job = self.load(d / "job.json")
            if job is None or (session_id and job.get("session_id") != session_id):
                continue
            found.append(job)
        found.sort(key=lambda j: (float(j.get("created") or 0), str(j.get("id", ""))), reverse=True)
        return found[:limit]


def chip_view(job: dict[str, Any]) -> dict[str, Any]:
    """The few fields the status chip and palette toasts need (no log, storyboard or QA)."""
    opts = job.get("options") or {}
    err = job.get("error") or {}
    return {
        "id": job.get("id"), "session_id": job.get("session_id", ""), "title": job.get("title") or "",
        "stage": job.get("stage"), "pct": job.get("pct"), "eta_s": job.get("eta_s"), "note": job.get("note") or "",
        "kind": job.get("kind") or "quick", "mode": opts.get("mode") or "product", "style": opts.get("style") or "",
        "created": job.get("created"), "updated": job.get("updated"), "finished": job.get("finished"),
        "outputs": sorted((job.get("outputs") or {}).keys()),
        "error": err.get("message", "") if isinstance(err, dict) else str(err),
    }


def active_jobs(jobs: list[dict[str, Any]], now: float, linger_s: float = 90.0) -> list[dict[str, Any]]:
    """Running jobs, plus jobs that finished in the last ``linger_s`` seconds (the chip says 'ready')."""
    out = []
    for job in jobs:
        stage = job.get("stage")
        finished = float(job.get("finished") or 0)
        if stage not in TERMINAL_STAGES or (finished and now - finished <= linger_s):
            out.append(chip_view(job))
    return out


# ----------------------------------------------------------------------------------- the Director

def _version_dirs(ddir: Path) -> list[tuple[int, Path]]:
    if not ddir.is_dir():
        return []
    found = []
    for d in ddir.iterdir():
        m = _VERSION_DIR.match(d.name)
        if m and d.is_dir():
            found.append((int(m.group(1)), d))
    return sorted(found)


def _sheet_ref(ddir: Path, raw: Any) -> dict[str, Any] | None:
    """A contact-sheet path from the log as ``{v, name}`` (paths never leave the backend)."""
    p = Path(str(raw or ""))
    if not _SHEET_NAME.match(p.name):
        return None
    m = _VERSION_DIR.match(p.parent.name)
    if not m or inside(ddir, p) is None:
        return None
    return {"v": int(m.group(1)), "name": p.name}


def read_log(ddir: Path, since: int = 0, limit: int = 400) -> tuple[list[dict[str, Any]], int]:
    """Director log entries from line ``since`` on (at most ``limit``) and the next ``since``.

    A trailing half-written line is not consumed: it is read again, whole, on the next poll.
    """
    path = ddir / "log.jsonl"
    try:
        raw = path.read_bytes()
    except OSError:
        return [], since
    complete = raw.split(b"\n")[:-1]      # the last piece is '' or a line still being written
    entries: list[dict[str, Any]] = []
    k = max(0, since)
    while k < len(complete) and len(entries) < limit:
        line = complete[k].strip()
        k += 1
        if not line:
            continue
        try:
            e = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        entry: dict[str, Any] = {"i": k - 1, "t": e.get("t"), "step": str(e.get("step") or ""),
                                 "level": str(e.get("level") or "info"), "msg": clip(e.get("msg"), MSG_CAP)}
        if isinstance(e.get("scores"), dict):
            entry["scores"] = {str(a): b for a, b in e["scores"].items() if isinstance(b, (int, float))}
        for key in ("product_share", "product_hero"):
            if isinstance(e.get(key), (int, float)):
                entry[key] = e[key]
        if isinstance(e.get("acts"), list):
            entry["acts"] = [clip(a, 120) for a in e["acts"][:8]]
        if isinstance(e.get("sheets"), list):
            refs = [r for r in (_sheet_ref(ddir, s) for s in e["sheets"][:12]) if r]
            if refs:
                entry["sheets"] = refs
        entries.append(entry)
    return entries, k


def treatment_summary(ddir: Path) -> dict[str, Any] | None:
    """The treatment's headline fields (title, logline, acts, requirements), or None before it exists."""
    t = read_json(ddir / "treatment.json")
    if not isinstance(t, dict):
        return None
    acts = []
    for a in t.get("acts") or []:
        if isinstance(a, dict):
            acts.append({"name": clip(a.get("name"), 80), "style": clip(a.get("style"), 40),
                         "duration": a.get("duration") if isinstance(a.get("duration"), (int, float)) else None,
                         "world": clip(a.get("world"), 240)})
    reqs = [clip(r.get("text") if isinstance(r, dict) else r, 120) for r in (t.get("requirements") or [])[:8]]
    return {"title": clip(t.get("title"), 80), "logline": clip(t.get("logline"), 400),
            "signature_moment": clip(t.get("signature_moment"), 300), "cta": clip(t.get("cta"), 120),
            "acts": acts[:8], "requirements": [r for r in reqs if r]}


def _score_from_critique(crit: Any) -> dict[str, Any] | None:
    if not isinstance(crit, dict) or not isinstance(crit.get("scores"), dict):
        return None
    scores = {k: float(v) for k, v in crit["scores"].items() if isinstance(v, (int, float))}
    vals = [scores[k] for k in RUBRIC if k in scores]
    if not vals:
        return None
    return {"scores": scores, "mean": round(sum(vals) / len(vals), 2), "min": min(vals),
            "verdict": clip(crit.get("verdict"), 40), "issues": len(crit.get("per_shot_issues") or [])}


def versions(ddir: Path) -> list[dict[str, Any]]:
    """Every version the Director built: its custom scenes, contact sheets, keyframes, score and changes."""
    state = read_json(ddir / "state.json")
    state_scores = {}
    if isinstance(state, dict):
        for v in state.get("versions") or []:
            if isinstance(v, dict) and isinstance(v.get("score"), dict):
                state_scores[v.get("n")] = v["score"]
    out = []
    for n, vdir in _version_dirs(ddir):
        scenes = []
        for p in sorted((vdir / "scenes").glob("*.js")) if (vdir / "scenes").is_dir() else []:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            scenes.append({"name": p.stem, "lines": text.count("\n") + 1, "bytes": len(text.encode("utf-8"))})
        sheets = sorted((p.name for p in vdir.glob("contact-*.jpg") if _SHEET_NAME.match(p.name)),
                        key=lambda s: int(re.sub(r"\D", "", s) or 0))
        kdir = vdir / "keyframes"
        keyframes = sorted(p.name for p in kdir.glob("*.png")) if kdir.is_dir() else []
        score = _score_from_critique(read_json(vdir / "critique.json"))
        st = state_scores.get(n)
        if isinstance(st, dict):
            score = dict(score or {}, **{k: st[k] for k in ("mean", "min", "passed", "product_share", "product_hero",
                                                              "round", "verdict") if k in st})
            if isinstance(st.get("scores"), dict):
                score["scores"] = st["scores"]
        changes = read_json(vdir / "changes.json")
        film = read_json(vdir / "film.json")
        shots = []
        if isinstance(film, dict):
            for s in (film.get("shots") or [])[:40]:
                if isinstance(s, dict):
                    shots.append({"id": clip(s.get("id"), 40), "t0": s.get("t0"), "t1": s.get("t1"),
                                  "scene": clip(s.get("scene"), 80)})
        out.append({"n": n, "scenes": scenes, "sheets": sheets, "keyframes": len(keyframes),
                    "keyframe_names": keyframes[:60], "score": score, "shots": shots,
                    "title": clip(film.get("title"), 80) if isinstance(film, dict) else "",
                    "changes": [clip(c, 400) for c in changes[:12]] if isinstance(changes, list) else []})
    return out


def usage(ddir: Path) -> dict[str, Any]:
    """Model calls so far: count, failures, tokens in/out, seconds (summed from ``calls/*.meta.json``)."""
    calls = ok = 0
    tin = tout = 0
    secs = 0.0
    cdir = ddir / "calls"
    for p in sorted(cdir.glob("*.meta.json")) if cdir.is_dir() else []:
        meta = read_json(p)
        if not isinstance(meta, dict):
            continue
        calls += 1
        ok += 1 if meta.get("ok") else 0
        u = meta.get("usage")
        u = u if isinstance(u, dict) else {}
        tin += int(u.get("input_tokens") or 0)
        tout += int(u.get("output_tokens") or 0)
        secs += float(meta.get("seconds") or 0.0)
    return {"calls": calls, "ok": ok, "input_tokens": tin, "output_tokens": tout, "seconds": round(secs, 1)}


def director_payload(job_dir: Path, since: int = 0, limit: int = 400, bar: float = 8.0) -> dict[str, Any]:
    """Everything the pane's 'watch the Director work' panel shows, read from ``<job>/director/``."""
    ddir = job_dir / "director"
    entries, nxt = read_log(ddir, since, limit)
    vers = versions(ddir)
    latest = vers[-1] if vers else None
    coded = {s["name"] for v in vers for s in v["scenes"]}
    coding: list[str] = []
    all_entries = entries if since == 0 else read_log(ddir, 0, 5000)[0]
    for e in all_entries:
        m = _CODING.match(e.get("msg") or "")
        if m and m.group(1) not in coded and m.group(1) not in coding:
            coding.append(m.group(1))
    result = read_json(ddir / "result.json")
    res = None
    if isinstance(result, dict):
        res = {k: result.get(k) for k in ("ok", "status", "version", "passed_bar", "seconds", "fallback", "error")}
        res["library_saved"] = [str(x) for x in (result.get("library_saved") or [])][:20]
    state = read_json(ddir / "state.json")
    best = state.get("best") if isinstance(state, dict) else None
    return {"available": ddir.is_dir(), "since": since, "next": nxt, "entries": entries,
            "treatment": treatment_summary(ddir), "versions": vers, "best": best,
            "latest": latest["n"] if latest else None, "coding": coding, "usage": usage(ddir), "result": res,
            "bar": bar, "rubric": list(RUBRIC)}


def scene_code(job_dir: Path, version: int, name: str, limit: int = 60_000) -> dict[str, Any] | None:
    """One custom scene's code as the Director wrote it (for the pane's code peek), or None."""
    if not _SCENE_NAME.match(name or ""):
        return None
    ddir = job_dir / "director"
    p = inside(ddir, ddir / f"v{int(version)}" / "scenes" / f"{name}.js")
    if p is None or not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return {"v": int(version), "name": name, "code": text[:limit], "truncated": len(text) > limit,
            "lines": text.count("\n") + 1}


def director_image_path(job_dir: Path, version: int, name: str) -> Path | None:
    """A contact sheet (``contact-N.jpg``) or keyframe (``NN-shot.png``) of one version, confined to the job."""
    ddir = job_dir / "director"
    vdir = ddir / f"v{int(version)}"
    if _SHEET_NAME.match(name or ""):
        cand = vdir / name
    elif _KEYFRAME_NAME.match(name or ""):
        cand = vdir / "keyframes" / name
    else:
        return None
    p = inside(ddir, cand)
    return p if p is not None and p.is_file() else None


class ImageCache:
    """Downscaled JPEG data URLs of contact sheets/keyframes (LRU keyed by path, mtime, size, width)."""

    def __init__(self, cap: int = 48) -> None:
        self._cap = cap
        self._items: OrderedDict[tuple[str, int, int, int], dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, path: Path, max_w: int, raw_limit: int = 3 * 1024 * 1024) -> dict[str, Any]:
        """``{url, w, h}``: a JPEG at most ``max_w`` wide (Pillow), else the original when small enough."""
        try:
            st = path.stat()
        except OSError:
            return {"url": "", "w": 0, "h": 0}
        key = (str(path), st.st_mtime_ns, st.st_size, max_w)
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        out = _downscale(path, max_w) or {"url": data_url(path, raw_limit), "w": 0, "h": 0}
        with self._lock:
            self._items[key] = out
            while len(self._items) > self._cap:
                self._items.popitem(last=False)
        return out


def _downscale(path: Path, max_w: int) -> dict[str, Any] | None:
    try:
        from PIL import Image  # Hermes core dependency; optional here
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            if im.width > max_w:
                im = im.resize((max_w, max(1, round(im.height * max_w / im.width))), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82, optimize=True)
            w, h = im.width, im.height
    except Exception:  # noqa: BLE001 - a broken or half-written image is just not shown yet
        return None
    return {"url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii"), "w": w, "h": h}


# ----------------------------------------------------------------------------------- the library

def library_items(lib_dir: Path, thumb_limit: int = LIBRARY_THUMB_LIMIT) -> list[dict[str, Any]]:
    """The user's saved scenes/worlds: ``<lib>/<name>/meta.json`` (+ ``thumb.jpg``), also one level of
    kind folders (``<lib>/worlds/<name>/``). Newest first."""
    if not lib_dir.is_dir():
        return []
    folders: list[tuple[Path, str]] = []
    for d in sorted(lib_dir.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        if (d / "meta.json").is_file():
            folders.append((d, ""))
        else:
            kind = d.name[:-1] if d.name.endswith("s") else d.name
            folders += [(sub, kind) for sub in sorted(d.iterdir()) if sub.is_dir() and (sub / "meta.json").is_file()]
    items = []
    for d, kind in folders:
        meta = read_json(d / "meta.json")
        if not isinstance(meta, dict):
            continue
        thumb_name = str(meta.get("thumbnail") or "thumb.jpg")
        thumb = inside(d, d / thumb_name)
        scores = meta.get("scores")
        mean = None
        if isinstance(scores, dict):
            vals = [float(v) for k, v in scores.items() if k in RUBRIC and isinstance(v, (int, float))]
            mean = round(sum(vals) / len(vals), 1) if vals else None
        try:
            mtime = (d / "meta.json").stat().st_mtime
        except OSError:
            mtime = 0.0
        items.append({
            "id": str(meta.get("id") or f"lib:{d.name}"), "name": str(meta.get("name") or d.name),
            "kind": str(meta.get("kind") or kind or "scene"), "describe": clip(meta.get("describe"), 400),
            "layer": str(meta.get("layer") or ""), "tags": [clip(t, 24) for t in (meta.get("tags") or [])[:8]],
            "kits": [clip(k, 24) for k in (meta.get("kits") or [])[:8]],
            "created_job": str(meta.get("created_job") or ""), "direction": clip(meta.get("direction"), 200),
            "score": mean, "path": str(d), "modified": mtime,
            "thumb": data_url(thumb, thumb_limit) if thumb is not None else "",
            "params": sorted((meta.get("params") or {}).keys())[:16] if isinstance(meta.get("params"), dict) else [],
        })
    items.sort(key=lambda i: i["modified"], reverse=True)
    return items


# ----------------------------------------------------------------------------------- post text

_MODE_LINES = {
    "product": "Cut from the real Hermes Agent session that built it: real code, real terminal output, real numbers.",
    "making_of": "The making-of, told by the Hermes Agent session that built it.",
    "speedrun": "Built as a speedrun: every split is a real timestamp from the Hermes Agent session.",
}


def post_text(job: dict[str, Any], tagline: str = "", logline: str = "") -> str:
    """A ready-to-post caption for the finished film (≤ 280 characters where the title allows)."""
    opts = job.get("options") or {}
    title = clip(job.get("title") or "My film", 60)
    directed = bool(str(opts.get("direction") or "").strip()) or job.get("kind") == "directed"
    style = str(opts.get("style") or "").strip()
    dur = job.get("duration_s") or opts.get("seconds")
    tail = "\n\n#HermesAgent #Auteur"
    if directed:
        body = "Directed from one line of text with /auteur in Hermes Agent."
        hook = logline or tagline
    else:
        body = _MODE_LINES.get(str(opts.get("mode") or "product"), _MODE_LINES["product"])
        made = "Made with /auteur" + (f" ({style}, {round(float(dur))} s)." if style and dur else ".")
        body = f"{body} {made}"
        hook = tagline
    head = f"{title}: {hook}" if hook else title
    room = 280 - len(tail) - len(body) - 2
    if len(head) > room:
        head = clip(head, max(len(title), room))
    return f"{head}\n\n{body}{tail}"
