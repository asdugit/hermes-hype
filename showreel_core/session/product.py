"""Product inference: what did this session BUILD? (product-first film mode, contracts.Product).

:func:`infer_product` scans extracted events and

* emits ``artifact`` events for deliverables (web pages, images, video, audio, PDFs, docs, data,
  entry-point code) written by the session, mentioned as saved by a command, or handed to the user
  in a reply (``MEDIA:`` tags / absolute paths in assistant answers);
* collects product evidence: name candidates (README H1, package.json / pyproject / Cargo /
  plugin.yaml names, HTML ``<title>``, repo/project directory, session title), one-liner
  candidates, local and deployed URLs/ports, run/dev/demo commands, entry files, feature bullets;
* flags screenshots that show the product (``data.product_shot``) so weights rank them highest;
* returns a :class:`~showreel_core.contracts.Product` draft plus the evidence (with event ids).

Artifact ``data``: ``{path, kind, preview_path, src, src_key, exists, bytes, source, ref_ids,
title?, lang?, delivered?}``. ``path`` is the deliverable's original location (home-relative after
redaction, still openable via ``expanduser``); ``preview_path`` is filled by asset collection
(image artifacts) or from a linked screenshot (web artifacts).
"""
from __future__ import annotations

import json
import re
import tomllib
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..contracts import Event, Product
from .assets import resolve_local
from .textutil import basename, clip, is_local_path, norm_path, short_path

ARTIFACT_KINDS: dict[str, str] = {
    **dict.fromkeys(("html", "htm"), "web"),
    **dict.fromkeys(("png", "jpg", "jpeg", "webp", "gif", "svg", "bmp"), "image"),
    **dict.fromkeys(("mp4", "webm", "mov", "mkv", "avi"), "video"),
    **dict.fromkeys(("mp3", "wav", "ogg", "m4a", "flac", "opus"), "audio"),
    "pdf": "pdf",
    **dict.fromkeys(("md", "docx", "pptx", "rst", "odt", "epub"), "doc"),
    **dict.fromkeys(("csv", "xlsx", "parquet", "ipynb", "geojson", "sqlite"), "data"),
    **dict.fromkeys(("zip", "exe", "apk", "dmg", "whl", "vsix", "rbxl", "rbxlx", "blend", "glb", "gltf", "stl"), "other"),
}
ENTRY_NAMES = {"index.html", "main.py", "app.py", "server.py", "cli.py", "__main__.py", "main.js", "index.js",
               "server.js", "app.js", "main.ts", "index.ts", "main.rs", "main.go", "app.tsx", "main.tsx", "app.jsx",
               "game.js", "main.lua", "plugin.yaml", "manifest.json", "readme.md", "streamlit_app.py", "gradio_app.py"}
_SKIP_DIRS = re.compile(r"(?i)(?:^|/)(?:node_modules|\.git|__pycache__|\.venv|venv|site-packages|dist-packages|"
                        r"\.cache|\.pytest_cache)(?:/|$)")
_LOCAL_URL_RE = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\]|[\w\-]+\.local)(?::\d{2,5})?(?:/[^\s\"'<>)\]]*)?", re.I)
_DEPLOY_URL_RE = re.compile(
    r"https://[\w.\-]+\.(?:vercel\.app|netlify\.app|pages\.dev|github\.io|fly\.dev|onrender\.com|herokuapp\.com|"
    r"railway\.app|surge\.sh|web\.app|firebaseapp\.com|azurewebsites\.net|deno\.dev|workers\.dev|glitch\.me|"
    r"replit\.app|streamlit\.app)(?:/[^\s\"'<>)\]]*)?|https://huggingface\.co/spaces/[\w.\-]+/[\w.\-]+", re.I)
_PORT_RE = re.compile(r"(?i)(?:listening|running|serving|started|available)\b[^\n]{0,40}?\bport\s*[:=]?\s*(\d{2,5})")
_RUN_CMD_RE = re.compile(
    r"(?i)(?:^|&&|;|\|\|)\s*((?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:dev|start|serve|preview|demo)\b[^\n&|;]*"
    r"|npx\s+(?:vite|next|serve|http-server|live-server|astro|remix|expo)\b[^\n&|;]*"
    r"|(?:vite|next\s+dev|astro\s+dev)\b[^\n&|;]*"
    r"|(?:python3?|py|uv\s+run(?:\s+python)?)\s+(?:-m\s+(?:http\.server|flask|streamlit|gradio|uvicorn|"
    r"[\w.]+\.(?:app|main|server|cli))|[\w./\\\-]*?(?:app|main|server|run|demo|game|serve|cli|play)\.py)\b[^\n&|;]*"
    r"|(?:uvicorn|gunicorn|hypercorn|flask\s+run|streamlit\s+run|gradio|fastapi\s+(?:dev|run))\b[^\n&|;]*"
    r"|cargo\s+run\b[^\n&|;]*|go\s+run\b[^\n&|;]*|deno\s+(?:run|task)\b[^\n&|;]*"
    r"|node\s+[\w./\\\-]*?(?:server|index|app|main)\.m?js\b[^\n&|;]*"
    r"|docker[\s-]compose\s+up\b[^\n&|;]*|make\s+(?:run|dev|serve|demo)\b[^\n&|;]*"
    r"|php\s+-S\b[^\n&|;]*|hugo\s+server\b[^\n&|;]*|jekyll\s+serve\b[^\n&|;]*|love\s+\.[^\n&|;]*)")
_H1_RE = re.compile(r"^#\s+(.+?)\s*#*\s*$", re.M)
_TITLE_RE = re.compile(r"<title[^>]*>\s*([^<]{2,120}?)\s*</title>", re.I)
_META_DESC_RE = re.compile(r"<meta\s+name=[\"']description[\"']\s+content=[\"']([^\"']{8,300})", re.I)
_HTML_HEAD_RE = re.compile(r"<h[23][^>]*>\s*([^<]{3,80}?)\s*</h[23]>", re.I)
_REMOTE_RE = re.compile(r"(?:github\.com|gitlab\.com|codeberg\.org)[/:]([\w.\-]+)/([\w.\-]+?)(?:\.git)?(?=[\s\"'/]|$)")
_ABS_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|~[\\/]|/)[^\s\"'`<>|*?]+\.(\w{2,8})\b")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")

MAX_ARTIFACTS = 24
MAX_PER_KIND = 8


@dataclass
class ProductReport:
    """Product draft + the evidence behind it (all values verbatim from the session)."""
    product: Product
    detected: bool = False
    confidence: float = 0.0
    evidence: dict[str, Any] = field(default_factory=dict)


def artifact_kind(path: str) -> str:
    """web|image|video|audio|pdf|doc|data|code|other for a file name ("" if not a deliverable type)."""
    name = basename(path).lower()
    if "." not in name:
        return ""
    ext = name.rsplit(".", 1)[-1]
    if ext in ARTIFACT_KINDS:
        return ARTIFACT_KINDS[ext]
    if name in ENTRY_NAMES:
        return "code"
    return ""


def _strip_md(s: str) -> str:
    s = _MD_LINK_RE.sub(r"\1", s)
    s = re.sub(r"[*_`]+", "", s)
    s = re.sub(r"<[^>]+>", "", s)
    return " ".join(s.split()).strip(" :-—")


def _readme_bits(lines: list[str]) -> tuple[str, str, list[str]]:
    """(H1, first sentence after it, feature bullets) from README markdown."""
    text = "\n".join(lines)
    h1m = _H1_RE.search(text)
    h1 = _strip_md(h1m.group(1)) if h1m else ""
    one = ""
    after = text[h1m.end():] if h1m else text
    for para in re.split(r"\n\s*\n", after):
        p = para.strip()
        if not p or p.startswith(("#", "!", "[!", "<", "|", "```", "-", "*", ">")) or p.startswith("[") and "](" in p[:80]:
            continue
        one = _strip_md(re.split(r"(?<=[.!?])\s", p.replace("\n", " "), maxsplit=1)[0])
        break
    feats: list[str] = []
    sec = re.search(r"^#{2,3}\s+(?:key\s+)?(?:features|highlights|what it does|what you get)\b.*$", text, re.I | re.M)
    block = text[sec.end():] if sec else after
    for line in block.split("\n"):
        if sec and re.match(r"^#{1,3}\s", line):
            break
        m = re.match(r"^\s*[-*+]\s+(.{3,})$", line)
        if m:
            f = _strip_md(m.group(1))
            f = re.split(r"\s+[—–-]\s+|:\s", f, maxsplit=1)[0] if len(f) > 60 else f
            if 3 <= len(f) <= 80:
                feats.append(f)
        elif feats and not sec and line.strip() and not line.startswith(" "):
            break
        if len(feats) >= 6:
            break
    return h1, one, feats


def _manifest_bits(name: str, lines: list[str]) -> dict[str, Any]:
    text = "\n".join(lines)
    out: dict[str, Any] = {}
    try:
        if name == "package.json":
            j = json.loads(text)
            out = {"name": j.get("name"), "description": j.get("description"), "bin": bool(j.get("bin")),
                   "scripts": list((j.get("scripts") or {}).keys()), "deps": list((j.get("dependencies") or {}).keys())}
        elif name in ("pyproject.toml", "cargo.toml"):
            t = tomllib.loads(text)
            proj = t.get("project") or t.get("package") or (t.get("tool", {}).get("poetry") or {})
            out = {"name": proj.get("name"), "description": proj.get("description"),
                   "bin": bool(proj.get("scripts") or t.get("bin") or (t.get("project", {}) or {}).get("scripts"))}
        elif name == "plugin.yaml":
            for key in ("name", "description"):
                m = re.search(rf"^{key}:\s*[\"']?(.+?)[\"']?\s*$", text, re.M)
                if m:
                    out[key] = m.group(1)
            out["plugin"] = True
        elif name == "go.mod":
            m = re.search(r"^module\s+(\S+)", text, re.M)
            if m:
                out["name"] = m.group(1).rsplit("/", 1)[-1]
        elif name == "setup.py":
            m = re.search(r"name\s*=\s*[\"']([^\"']+)", text)
            if m:
                out["name"] = m.group(1)
    except (ValueError, tomllib.TOMLDecodeError, AttributeError, TypeError):
        return {}
    return {k: v for k, v in out.items() if v}


class _Evidence:
    def __init__(self) -> None:
        self.names: list[tuple[float, str, str, str]] = []        # (score, name, source, event id)
        self.one_liners: list[tuple[float, str, str, str]] = []
        self.urls: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self.ports: Counter[int] = Counter()
        self.run_cmds: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
        self.features: list[tuple[str, str]] = []
        self.kind_votes: Counter[str] = Counter()

    def name(self, score: float, value: Any, source: str, eid: str) -> None:
        v = clip(str(value or "").strip().strip("\"'"), 60)
        if v and len(v) >= 2 and not v.lower().startswith(("untitled", "document", "readme", "index")):
            self.names.append((score, v, source, eid))

    def url(self, url: str, source: str, eid: str, score: float) -> None:
        u = url.rstrip(".,;:)]'\"/") or url
        cur = self.urls.get(u)
        if cur is None:
            self.urls[u] = {"url": u, "source": source, "ids": [eid], "score": score}
        else:
            cur["score"] = max(cur["score"], score)
            if eid not in cur["ids"]:
                cur["ids"].append(eid)


def _path_ok(path: str) -> bool:
    p = norm_path(path)
    return bool(p) and not _SKIP_DIRS.search(p)


_ROOT_MARKERS = (".git", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "plugin.yaml", "setup.py",
                 "README.md", "readme.md", "index.html")


def _project_root(paths: list[str]) -> str:
    """Project directory of the written files: the majority common dir, walked up to the nearest
    directory holding a project marker (.git, package.json, pyproject.toml, README.md, ...)."""
    dirs = [norm_path(p).rsplit("/", 1)[0] for p in paths if "/" in norm_path(p)]
    if not dirs:
        return ""
    counts: Counter[str] = Counter()
    for d in dirs:
        parts = d.split("/")
        for i in range(1, len(parts) + 1):
            counts["/".join(parts[:i])] += 1
    need = max(2, int(len(dirs) * 0.6))
    best = ""
    for d, c in counts.items():
        if c >= need and d.count("/") > best.count("/"):
            best = d
    if not best:
        return ""
    probe = resolve_local(best)
    for _ in range(6):
        if probe is None:
            break
        try:
            if any((probe / m).exists() for m in _ROOT_MARKERS):
                return probe.as_posix()
        except OSError:
            break
        if probe.parent == probe or len(probe.parts) <= 3:   # never climb to a drive/home root
            break
        probe = probe.parent
    return best


def infer_product(events: list[Event], meta: dict[str, Any] | None = None) -> ProductReport:
    """Infer the product and insert ``artifact`` events into ``events`` (ids are renumbered). Never raises."""
    meta = meta or {}
    try:
        return _infer(events, meta)
    except Exception as exc:  # pragma: no cover - defensive
        return ProductReport(product=Product(), evidence={"error": f"{type(exc).__name__}: {exc}"})


def _infer(events: list[Event], meta: dict[str, Any]) -> ProductReport:
    ev_ = _Evidence()
    cands: "OrderedDict[str, dict[str, Any]]" = OrderedDict()   # path key -> artifact draft
    written: list[str] = []
    html_pages: dict[str, Event] = {}

    def candidate(path: str, ev: Event, source: str, delivered: bool = False, **extra: Any) -> None:
        kind = artifact_kind(path)
        if not kind or not _path_ok(path):
            return
        key = norm_path(path)
        cur = cands.get(key)
        if cur is None:
            cands[key] = cur = {"path": path, "kind": kind, "ref_ids": [], "source": source, "delivered": False,
                                "anchor": ev, "t": ev.t, **extra}
        cur["ref_ids"].append(ev.id)
        cur["anchor"], cur["t"] = ev, ev.t
        cur["delivered"] = cur["delivered"] or delivered
        cur.update({k: v for k, v in extra.items() if v})

    for ev in events:
        d = ev.data
        if ev.kind in ("file_write", "file_patch") and ev.ok:
            path = str(d.get("path") or "")
            name = basename(path).lower()
            if path:
                written.append(path)
            lines = d.get("lines") if ev.kind == "file_write" else None
            title = ""
            if lines and name.endswith((".html", ".htm")):
                head = "\n".join(lines[:80])
                tm = _TITLE_RE.search(head)
                title = _strip_md(tm.group(1)) if tm else ""
                if tm:
                    ev_.name(0.7 if name == "index.html" else 0.55, title, f"<title> of {short_path(path, 2)}", ev.id)
                dm = _META_DESC_RE.search(head)
                if dm:
                    ev_.one_liners.append((0.7, clip(dm.group(1), 90), "meta description", ev.id))
                if not ev_.features:
                    heads = [_strip_md(h) for h in _HTML_HEAD_RE.findall("\n".join(lines))]
                    ev_.features += [(h, ev.id) for h in heads[:6] if 3 <= len(h) <= 60]
                html_pages[norm_path(path)] = ev
            if ev.kind == "file_write" or d.get("action") == "add":
                candidate(path, ev, "written", title=title, lang=d.get("lang", ""))
            elif name in ENTRY_NAMES or name.endswith((".html", ".htm")):
                candidate(path, ev, "edited", title=title, lang=d.get("lang", ""))
            if lines:
                _scan_key_file(ev_, name, path, lines, ev.id)
        elif ev.kind == "file_read" and d.get("content_lines"):
            _scan_key_file(ev_, basename(str(d.get("path") or "")).lower(), str(d.get("path") or ""),
                           d["content_lines"], ev.id, read=True)
        elif ev.kind == "terminal":
            cmd = str(d.get("cmd") or "")
            for m in _RUN_CMD_RE.finditer(cmd if d.get("shell") != "python" else ""):
                c = clip(m.group(1).strip(), 120)
                slot = ev_.run_cmds.setdefault(c, {"cmd": c, "ids": [], "ok": False})
                slot["ids"].append(ev.id)
                slot["ok"] = slot["ok"] or ev.ok
            out = "\n".join(d.get("output_lines") or [])
            for u in d.get("urls") or []:
                if _LOCAL_URL_RE.fullmatch(u.rstrip("/")) or _LOCAL_URL_RE.match(u):
                    ev_.url(u, "terminal output", ev.id, 0.6)
                elif _DEPLOY_URL_RE.match(u):
                    ev_.url(u, "deploy output", ev.id, 0.9)
            for m in _PORT_RE.finditer(out):
                ev_.ports[int(m.group(1))] += 1
            for m in _REMOTE_RE.finditer(cmd + "\n" + out):
                if "git" in cmd or "gh " in cmd:
                    ev_.name(0.5, m.group(2), "git remote", ev.id)
            for p in d.get("saved_paths") or []:
                if is_local_path(p) or "/" in p or "\\" in p:
                    candidate(p, ev, "saved by command")
        elif ev.kind == "browser_nav":
            for u in d.get("urls") or [d.get("url") or ""]:
                if _LOCAL_URL_RE.match(u or ""):
                    ev_.url(u, "browser", ev.id, 0.8)
                elif _DEPLOY_URL_RE.match(u or ""):
                    ev_.url(u, "browser", ev.id, 0.95)
                elif (u or "").startswith("file://"):
                    ev_.url(u, "browser (local file)", ev.id, 0.7)
        elif ev.kind in ("final_answer", "assistant_note") and d.get("turn_end") is not False:
            text = str(d.get("text") or "")
            refs = list(d.get("media") or [])
            refs += [m.group(0) for m in _ABS_PATH_RE.finditer(text) if artifact_kind(m.group(0))]
            for p in dict.fromkeys(refs):
                candidate(p.strip("`'\".,)"), ev, "handed to user", delivered=True)
            for u in _DEPLOY_URL_RE.findall(text):
                ev_.url(u, "final answer", ev.id, 1.0)
            for u in _LOCAL_URL_RE.findall(text):
                ev_.url(u, "answer", ev.id, 0.7)

    # ---- name / one-liner fallbacks
    root = _project_root(written)
    if root:
        ev_.name(0.45, basename(root), "project directory", "")
    if meta.get("git_repo_root"):
        ev_.name(0.5, basename(str(meta["git_repo_root"])), "git repo root", "")
    if meta.get("title"):
        ev_.name(0.25, meta["title"], "session title", "")

    # ---- artifacts: rank, cap, emit
    ranked = sorted(cands.values(), key=lambda c: (not c["delivered"], c["kind"] in ("code", "doc", "data"),
                                                   -c["t"]))
    per_kind: Counter[str] = Counter()
    chosen: list[dict[str, Any]] = []
    for c in ranked:
        if len(chosen) >= MAX_ARTIFACTS or per_kind[c["kind"]] >= MAX_PER_KIND:
            continue
        if c["kind"] in ("code",) and basename(c["path"]).lower() not in ENTRY_NAMES:
            continue
        if c["kind"] == "doc" and not c["delivered"] and basename(c["path"]).lower() != "readme.md" and c["source"] != "written":
            continue
        per_kind[c["kind"]] += 1
        chosen.append(c)
    counts = Counter(c["kind"] for c in cands.values())
    new_events: list[tuple[Event, Event]] = []
    for c in chosen:
        p = resolve_local(c["path"])
        exists, size = False, None
        try:
            if p is not None and p.is_file():
                exists, size = True, p.stat().st_size
        except OSError:
            pass
        label = short_path(c["path"], 2)
        data = {"path": c["path"], "kind": c["kind"], "preview_path": "", "src": c["path"],
                "src_key": norm_path(c["path"]), "exists": exists, "bytes": size, "source": c["source"],
                "ref_ids": list(dict.fromkeys(c["ref_ids"]))[-6:], "delivered": c["delivered"]}
        if c.get("title"):
            data["title"] = c["title"]
        if c.get("lang"):
            data["lang"] = c["lang"]
        verb = "delivered" if c["delivered"] else c["source"]
        art = Event(id="", t=c["t"], kind="artifact", tool="", title=label,
                    summary=clip(f"{c['kind']} artifact {label} ({verb})", 160), data=data, ok=exists)
        new_events.append((c["anchor"], art))
    _insert_after(events, new_events)

    # ---- product screenshots: browser shots of product URLs / local pages, images that are deliverables
    product_urls = {u for u in ev_.urls}
    html_keys = set(html_pages)
    art_keys = {norm_path(c["path"]) for c in chosen}
    for ev in events:
        if ev.kind not in ("screenshot", "image_generated"):
            continue
        url = str(ev.data.get("url") or "")
        hit = any(url.startswith(u.rstrip("/")) for u in product_urls if u) or \
            (url.startswith("file://") and norm_path(url[7:].lstrip("/")) in html_keys) or \
            ev.data.get("src_key") in art_keys or ev.data.get("artifact")
        if hit:
            ev.data["product_shot"] = True
    for art in (e for e in events if e.kind == "artifact" and e.data.get("kind") == "web"):
        key = art.data.get("src_key")
        shots = [e.id for e in events if e.kind == "screenshot" and str(e.data.get("url") or "").startswith("file://")
                 and norm_path(str(e.data["url"])[7:].lstrip("/")) == key]
        if shots:
            art.data["screenshot_ids"] = shots[-4:]

    # ---- assemble Product
    names = sorted(ev_.names, key=lambda x: -x[0])
    seen_names: set[str] = set()
    name_list = []
    for s, n, src, eid in names:
        if n.lower() in seen_names:
            continue
        seen_names.add(n.lower())
        name_list.append({"name": n, "source": src, "score": s, "id": eid})
    ones = sorted(ev_.one_liners, key=lambda x: -x[0])
    urls = sorted(ev_.urls.values(), key=lambda u: -u["score"])
    entry = []
    for c in cands.values():
        if basename(c["path"]).lower() in ENTRY_NAMES and c["path"] not in entry:
            entry.append(c["path"])
    run_cmds = [r for r in ev_.run_cmds.values()]
    run_cmds.sort(key=lambda r: (not r["ok"], -len(r["ids"])))
    kind = _guess_kind(counts, ev_, entry, urls)
    feats = list(dict.fromkeys(f for f, _ in ev_.features))[:6]
    product = Product(
        name=name_list[0]["name"] if name_list else "",
        one_liner=ones[0][1] if ones else "",
        kind=kind,
        urls=[u["url"] for u in urls[:6]],
        entry_files=entry[:6],
        run_commands=[r["cmd"] for r in run_cmds[:5]],
        features=feats,
    )
    deliverable_kinds = {k for k in counts if k not in ("code", "doc")}
    detected = bool(product.urls or deliverable_kinds or (product.name and (entry or product.run_commands)))
    conf = 0.0
    conf += 0.3 if name_list and name_list[0]["score"] >= 0.5 else (0.1 if name_list else 0.0)
    conf += 0.25 if product.urls else 0.0
    conf += 0.2 if any(e.kind == "artifact" and e.data.get("exists") for e in events) else 0.0
    conf += 0.15 if product.run_commands else 0.0
    conf += 0.1 if product.one_liner or feats else 0.0
    evidence = {
        "names": name_list[:6],
        "one_liners": [{"text": t, "source": s, "id": i} for _, t, s, i in ones[:3]],
        "urls": urls[:8],
        "ports": [p for p, _ in ev_.ports.most_common(4)],
        "run_commands": run_cmds[:6],
        "entry_files": entry[:8],
        "features": [{"text": f, "id": i} for f, i in ev_.features[:6]],
        "artifact_counts": dict(counts),
        "artifact_ids": [e.id for e in events if e.kind == "artifact"],
        "product_shot_ids": [e.id for e in events if e.data.get("product_shot")][:12],
    }
    # rebuild weights now that artifacts/product shots are known
    from .weights import assign_weights
    assign_weights(events)
    product.hero_event_ids = [e.id for e in sorted(
        (e for e in events if (e.kind == "artifact" and e.data.get("exists") and e.data.get("kind") in ("web", "image", "video"))
         or e.data.get("product_shot")), key=lambda e: (-e.weight, -e.t))][:6]
    return ProductReport(product=product, detected=detected, confidence=round(min(1.0, conf), 2), evidence=evidence)


def _scan_key_file(ev_: _Evidence, name: str, path: str, lines: list[str], eid: str, read: bool = False) -> None:
    w = 0.85 if not read else 0.7       # files the session wrote outrank files it merely read
    if name.startswith("readme"):
        h1, one, feats = _readme_bits(lines)
        if h1:
            ev_.name(w + 0.05, h1, f"README H1 ({short_path(path, 2)})", eid)
        if one:
            ev_.one_liners.append((w, clip(one, 90), "README", eid))
        if feats and len(ev_.features) < 6:
            ev_.features = [(f, eid) for f in feats] + ev_.features
    elif name in ("package.json", "pyproject.toml", "cargo.toml", "plugin.yaml", "go.mod", "setup.py"):
        bits = _manifest_bits(name, lines)
        if bits.get("name"):
            ev_.name(w, bits["name"], f"{name} name", eid)
        if bits.get("description"):
            ev_.one_liners.append((w - 0.05, clip(str(bits["description"]), 90), f"{name} description", eid))
        if bits.get("bin"):
            ev_.kind_votes["cli"] += 2
        if bits.get("plugin"):
            ev_.kind_votes["other"] += 3
        deps = " ".join(bits.get("deps") or [])
        if re.search(r"\b(react|vue|svelte|next|vite|astro|solid-js)\b", deps):
            ev_.kind_votes["web_app"] += 2
        if re.search(r"\b(express|fastify|koa|hono)\b", deps):
            ev_.kind_votes["api"] += 1
        if re.search(r"\b(phaser|pixi\.js|three|kaboom)\b", deps):
            ev_.kind_votes["game"] += 2


def _guess_kind(counts: Counter[str], ev_: _Evidence, entry: list[str], urls: list[dict[str, Any]]) -> str:
    votes = Counter(ev_.kind_votes)
    entry_names = {basename(e).lower() for e in entry}
    if counts.get("web"):
        votes["web_app" if (urls or "index.html" in entry_names) else "site"] += 2 + min(3, counts["web"])
    if urls:
        votes["web_app"] += 2
    cmds = " ".join(ev_.run_cmds)
    if re.search(r"uvicorn|gunicorn|fastapi|flask", cmds):
        votes["api"] += 2
    if re.search(r"\blove\b|pygame|godot", cmds):
        votes["game"] += 3
    media = counts.get("video", 0) + counts.get("image", 0) + counts.get("audio", 0)
    if media:
        votes["media"] += min(4, media)
    if counts.get("pdf") or counts.get("doc"):
        votes["doc"] += 1 + min(2, counts.get("pdf", 0) + counts.get("doc", 0) // 3)
    if counts.get("data"):
        votes["data"] += min(3, counts["data"])
    if entry_names & {"main.py", "cli.py", "__main__.py", "main.rs", "main.go"} and not votes:
        votes["cli"] += 1
    if not votes:
        return ""
    return votes.most_common(1)[0][0]


def _insert_after(events: list[Event], pairs: list[tuple[Event, Event]]) -> None:
    """Insert each new event right after its anchor; then renumber ids e0..eN (refs updated)."""
    if not pairs:
        return
    after: dict[int, list[Event]] = {}
    for anchor, new in pairs:
        after.setdefault(id(anchor), []).append(new)
    out: list[Event] = []
    for ev in events:
        out.append(ev)
        out.extend(after.get(id(ev), []))
    old_ids = {id(e): e.id for e in events}
    events[:] = out
    remap: dict[str, str] = {}
    for i, ev in enumerate(events):
        new_id = f"e{i}"
        if id(ev) in old_ids:
            remap[old_ids[id(ev)]] = new_id
        ev.id = new_id
    for ev in events:
        for key in ("ref_ids", "screenshot_ids"):
            if isinstance(ev.data.get(key), list):
                ev.data[key] = [remap.get(x, x) for x in ev.data[key]]
        if isinstance(ev.data.get("note"), str):
            ev.data["note"] = remap.get(ev.data["note"], ev.data["note"])


def link_previews(events: list[Event]) -> None:
    """After asset collection: give web artifacts the copied screenshot of their page as preview."""
    by_id = {e.id: e for e in events}
    for art in events:
        if art.kind != "artifact" or art.data.get("preview_path"):
            continue
        for sid in reversed(art.data.get("screenshot_ids") or []):
            shot = by_id.get(sid)
            if shot is not None and shot.data.get("path"):
                art.data["preview_path"] = shot.data["path"]
                art.data["preview_from"] = sid
                break


def product_section(report: ProductReport | None) -> list[str]:
    """Digest lines for the PRODUCT EVIDENCE section."""
    if report is None:
        return []
    p, ev = report.product, report.evidence
    lines = ["## PRODUCT EVIDENCE (the film is a launch trailer for this; cite ids)"]
    lines.append(f"detected: {'yes' if report.detected else 'no'} (confidence {report.confidence:.2f}) | kind guess: {p.kind or '?'}")
    names = ev.get("names") or []
    if names:
        lines.append("name candidates: " + "; ".join(
            f"\"{n['name']}\" ({n['source']}{', ' + n['id'] if n.get('id') else ''})" for n in names[:5]))
    for o in (ev.get("one_liners") or [])[:2]:
        lines.append(f"one-liner ({o['source']}, {o['id']}): \"{o['text']}\"")
    for u in (ev.get("urls") or [])[:5]:
        lines.append(f"url: {u['url']} ({u['source']}; {', '.join(u['ids'][:3])})")
    if ev.get("ports"):
        lines.append("ports: " + ", ".join(str(x) for x in ev["ports"]))
    for r in (ev.get("run_commands") or [])[:4]:
        lines.append(f"run: $ {r['cmd']} ({'ok' if r['ok'] else 'not confirmed'}; {', '.join(r['ids'][:3])})")
    if p.entry_files:
        lines.append("entry files: " + ", ".join(short_path(e, 3) for e in p.entry_files))
    if ev.get("features"):
        lines.append("features: " + "; ".join(f"{f['text']} ({f['id']})" for f in ev["features"]))
    counts = ev.get("artifact_counts") or {}
    if counts:
        lines.append("deliverables seen: " + ", ".join(f"{k} ×{v}" for k, v in sorted(counts.items(), key=lambda x: -x[1])))
    if p.hero_event_ids:
        lines.append("best product visuals: " + ", ".join(p.hero_event_ids))
    return lines
