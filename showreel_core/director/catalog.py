"""The model-facing reference: SDK, kit catalog, user library, product media, music/SFX and capabilities.

Everything is read from files at call time (kits/*/KIT.md + kit.js, plugin-data library, assets/audio/*),
so new kits and library entries show up without code changes. Parsing is deliberately forgiving: kit authors
document their kits in markdown, and the raw KIT.md text is what the model reads; the ids and param names we
extract are only used for validation and fallbacks.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .types import Capabilities, MediaAsset

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = Path(__file__).resolve().parent / "reference"

BUILTIN_TRANSITIONS = ("cut", "crossfade", "dip-black", "dip-white", "push-left", "push-right", "push-up", "whip",
                       "zoom-through", "iris", "wipe", "glitch", "pixelate", "film-burn", "ink-bleed", "page-turn")

_ID_RE = re.compile(r"\bkit:([a-z0-9][a-z0-9_-]*)/([a-z0-9][a-z0-9_.-]*[a-z0-9])")
_DEFINE_RE = re.compile(r"""define(Scene|Transition)\(\s*['"`]([^'"`]+)['"`]\s*,""")
_ID_FIELD_RE = re.compile(r"""\bid\s*:\s*['"`](kit:[a-z0-9_-]+/[a-z0-9_.-]+)['"`]""")
_DESCRIBE_RE = re.compile(r"""describe\s*:\s*(['"`])((?:\\.|(?!\1).)*)\1""", re.DOTALL)
_LAYER_RE = re.compile(r"""layer\s*:\s*['"`](2d|three|webgl|dom)['"`]""")


@dataclass
class SceneInfo:
    """A scene the film may reference (kit or library)."""
    id: str                          # kit:pixel/dungeon-walk | lib:boss-battle
    kit: str = ""                    # kit name ("" for library scenes)
    describe: str = ""
    layer: str = ""
    params: list[str] = field(default_factory=list)      # declared param names
    params_src: str = ""             # raw params literal (JS) for the model


@dataclass
class KitInfo:
    """One built-in kit: its catalog text and the ids it registers."""
    name: str
    path: str
    summary: str = ""
    doc: str = ""                    # KIT.md text
    scenes: list[SceneInfo] = field(default_factory=list)
    transitions: list[str] = field(default_factory=list)


@dataclass
class LibraryEntry:
    """A user-library scene (``lib:<name>``) saved by an earlier Director run or by hand."""
    name: str
    id: str
    describe: str = ""
    layer: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    thumbnail: str = ""
    path: str = ""                   # scene.js
    kits: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass
class Bed:
    """A music bed (from assets/audio/beds/<style>/bars.json)."""
    id: str
    style: str
    title: str = ""
    bpm: float = 120.0
    bar_s: float = 2.0
    duration_s: float = 0.0
    notes: str = ""
    sections: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Catalog:
    """What the Director may use. Build with :func:`build_catalog`."""
    kits: list[KitInfo] = field(default_factory=list)
    library: list[LibraryEntry] = field(default_factory=list)
    beds: list[Bed] = field(default_factory=list)
    sfx: dict[str, dict[str, Any]] = field(default_factory=dict)     # name -> {class, tags, dur}
    assets: list[MediaAsset] = field(default_factory=list)
    capabilities: Capabilities = field(default_factory=Capabilities)
    sdk: str = ""
    craft: str = ""

    # ------------------------------------------------------------------ lookups
    def scenes(self) -> dict[str, SceneInfo]:
        """Every referenceable scene id (kit + library) -> info."""
        out: dict[str, SceneInfo] = {}
        for k in self.kits:
            for s in k.scenes:
                out[s.id] = s
        for e in self.library:
            out[e.id] = SceneInfo(e.id, "", e.describe, e.layer, list(e.params), json.dumps(e.params)[:800])
        return out

    def transitions(self) -> set[str]:
        """Built-in transition names plus every kit transition id."""
        try:
            from ..film.schema import BUILTIN_TRANSITIONS as runtime_builtins
            out: set[str] = set(runtime_builtins)
        except ImportError:
            out = set(BUILTIN_TRANSITIONS)
        for k in self.kits:
            out.update(k.transitions)
        return out

    def bed(self, bed_id: str) -> Bed | None:
        return next((b for b in self.beds if b.id == bed_id), None)

    def stings(self) -> list[str]:
        """Sounds suited to mark a turn (risers, reverses, impacts)."""
        return sorted(n for n, s in self.sfx.items()
                      if s.get("class") == "hero" or {"build", "hero"} & set(s.get("tags") or []))

    def kit(self, name: str) -> KitInfo | None:
        return next((k for k in self.kits if k.name == name), None)

    @property
    def has_kits(self) -> bool:
        return any(k.scenes for k in self.kits)

    def asset_names(self) -> set[str]:
        return {a.name for a in self.assets}

    # ------------------------------------------------------------------ prompt text
    def overview(self) -> str:
        """Short catalog for the treatment step: what exists, one line each."""
        lines = ["## Kits (built-in scenes; the reliable floor)"]
        if not self.kits:
            lines.append("(no kits installed: every shot will be a custom scene)")
        for k in self.kits:
            lines.append(f"- **{k.name}**: {k.summary or '(no summary)'}")
            for s in k.scenes:
                lines.append(f"  - `{s.id}`{f' [{s.layer}]' if s.layer else ''}: {_one_line(s.describe, 160)}")
            if k.transitions:
                lines.append(f"  - transitions: {', '.join(f'`{t}`' for t in k.transitions)}")
        lines.append("\n## User library (reusable by id)")
        lines += [f"- `{e.id}` [{e.layer or '?'}]: {_one_line(e.describe, 200)}" for e in self.library] or ["(empty)"]
        lines.append("\n" + self.music_text())
        lines.append("\n" + self.assets_text())
        lines.append("\n" + self.capabilities_text())
        return "\n".join(lines)

    def full(self, *, kit_budget: int = 9000) -> str:
        """Catalog for the film step: overview + each kit's KIT.md (truncated per kit) + scene params."""
        parts = [self.overview(), "\n## Kit reference (KIT.md per kit)"]
        for k in self.kits:
            parts.append(f"\n### kit `{k.name}`\n{_clip(k.doc, kit_budget) if k.doc else '(no KIT.md)'}")
            declared = [s for s in k.scenes if s.params_src]
            if declared:
                parts.append("Registered scene params (from kit.js):")
                parts += [f"- `{s.id}` params: {_one_line(s.params_src, 700)}" for s in declared]
        if self.library:
            parts.append("\n### Library scene params")
            parts += [f"- `{e.id}`: {json.dumps(e.params, ensure_ascii=False)[:700]}" for e in self.library]
        parts.append(f"\nBuilt-in transitions: {', '.join(BUILTIN_TRANSITIONS)}")
        return "\n".join(parts)

    def kit_docs(self, names: list[str], *, budget: int = 14000) -> str:
        """KIT.md text of the named kits (for the scene-code step: building blocks to reuse)."""
        chosen = [k for k in self.kits if k.name in names] or []
        if not chosen:
            return "(no kit building blocks selected)"
        per = max(2000, budget // len(chosen))
        return "\n\n".join(f"### ctx.kit('{k.name}')\n{_clip(k.doc, per)}" for k in chosen)

    def music_text(self) -> str:
        lines = ["## Music beds (film.json music[].bed) - all original, bar-fitted automatically"]
        for b in self.beds:
            secs = " ".join(f"{s.get('name')}@bar{s.get('start_bar')}" for s in b.sections[:8])
            lines.append(f"- `{b.id}` ({b.style}, \"{b.title}\", {b.bpm:g} BPM, bar {b.bar_s:.2f}s, "
                         f"{b.duration_s:.0f}s natural): {_one_line(b.notes, 140)} [{secs}]")
        if not self.beds:
            lines.append("(no beds installed)")
        lines.append(f"Stings (music[].sting): {', '.join(self.stings()) or '(none)'}")
        lines.append("SFX (cues[].sfx): " + (", ".join(
            f"{n}({'/'.join(s.get('tags') or []) or s.get('class', '')})" for n, s in sorted(self.sfx.items()))
            or "(none)"))
        return "\n".join(lines)

    def assets_text(self) -> str:
        lines = ["## Product media (asset names for film.json and ctx.asset(name))"]
        for a in self.assets:
            dims = f"{a.w}x{a.h}" if a.w else "?"
            dur = f", {a.dur:.1f}s @ {a.fps:g} fps" if a.type == "video" and a.dur else ""
            lines.append(f"- `{a.name}`: {a.type} {dims}{dur}{' (product)' if a.product else ''}"
                         f"{': ' + a.description if a.description else ''}")
        if not self.assets:
            lines.append("(no product media: the product must be shown with type, UI or drawn elements)")
        return "\n".join(lines)

    def capabilities_text(self) -> str:
        c = self.capabilities
        return ("## Capabilities\n"
                f"- GPU: {'yes' if c.gpu else 'no (software WebGL: keep three.js scenes light)'}\n"
                f"- three.js: {'available' if c.three else 'not available'}\n"
                f"- image generation tool: {'available' if c.image_generate else 'not available'}; "
                f"video generation: {'available' if c.video_generate else 'not available'}")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("sdk", None)
        d.pop("craft", None)
        for k in d["kits"]:
            k["doc"] = _clip(k["doc"], 400)
        return d


# ---------------------------------------------------------------------- builders

def build_catalog(*, kits_dir: Path | None = None, library_dir: Path | None = None,
                  audio_dir: Path | None = None, assets: list[MediaAsset] | None = None,
                  capabilities: Capabilities | None = None) -> Catalog:
    """Read kits, library, audio metadata and the SDK reference into a :class:`Catalog`. Never raises."""
    kits_dir = kits_dir if kits_dir is not None else REPO_ROOT / "kits"
    audio_dir = audio_dir if audio_dir is not None else REPO_ROOT / "assets" / "audio"
    return Catalog(
        kits=load_kits(kits_dir), library=load_library(library_dir) if library_dir else [],
        beds=load_beds(audio_dir / "beds"), sfx=load_sfx(audio_dir / "sfx" / "sfx.json"),
        assets=list(assets or []), capabilities=capabilities or Capabilities(),
        sdk=_read(REFERENCE_DIR / "sdk.md"), craft=_read(REFERENCE_DIR / "craft.md"),
    )


def load_kits(kits_dir: Path) -> list[KitInfo]:
    """Parse every ``kits/<kit>/`` (KIT.md + kit.js + other .js files) into :class:`KitInfo`."""
    out: list[KitInfo] = []
    if not kits_dir.is_dir():
        return out
    for d in sorted(p for p in kits_dir.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        try:
            out.append(parse_kit(d))
        except OSError:
            continue
    return out


def parse_kit(d: Path) -> KitInfo:
    """One kit directory -> :class:`KitInfo` (ids from ``defineScene``/``defineTransition`` and KIT.md)."""
    doc = _read(d / "KIT.md")
    info = KitInfo(name=d.name, path=str(d), doc=doc, summary=_summary(doc))
    scenes: dict[str, SceneInfo] = {}
    transitions: list[str] = []
    for js in sorted(d.rglob("*.js")):
        if any(part in ("vendor", "node_modules", "tests") for part in js.relative_to(d).parts):
            continue
        src = _read(js)
        found = [(m.group(1), m.group(2), m.end()) for m in _DEFINE_RE.finditer(src)]
        # kit-style registration objects: export const x = { id: 'kit:pixel/dungeon-walk', def: { ... } }
        found += [("Transition" if m.group(1).startswith("kit:transitions/") else "Scene", m.group(1), m.end())
                  for m in _ID_FIELD_RE.finditer(src)]
        for kind, sid, end in found:
            if kind == "Transition":
                if sid not in transitions:
                    transitions.append(sid)
                continue
            window = _object_after(src, end)
            desc = _DESCRIBE_RE.search(window)
            layer = _LAYER_RE.search(window)
            psrc = _param_block(window, src)
            prev = scenes.get(sid)
            if prev and prev.describe and not desc:
                continue
            scenes[sid] = SceneInfo(sid, d.name, desc.group(2) if desc else "", layer.group(1) if layer else "",
                                    top_level_keys(psrc) if psrc else [], psrc)
    # no registrations found in JS (generated kit?): fall back to the ids KIT.md documents for this kit
    if not scenes and not transitions:
        for m in _ID_RE.finditer(doc):
            sid = m.group(0)
            if m.group(1) != d.name:
                continue
            if d.name == "transitions":
                if sid not in transitions:
                    transitions.append(sid)
            elif sid not in scenes:
                scenes[sid] = SceneInfo(sid, d.name, _describe_from_doc(doc, sid))
    for s in scenes.values():
        if not s.describe:
            s.describe = _describe_from_doc(doc, s.id)
    info.scenes = list(scenes.values())
    info.transitions = transitions
    return info


def load_library(library_dir: Path) -> list[LibraryEntry]:
    """Every ``<library>/<name>/meta.json`` (+ scene.js) as a :class:`LibraryEntry`."""
    out: list[LibraryEntry] = []
    if not library_dir or not Path(library_dir).is_dir():
        return out
    for d in sorted(p for p in Path(library_dir).iterdir() if p.is_dir()):
        meta_p, js = d / "meta.json", d / "scene.js"
        if not js.is_file():
            continue
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.is_file() else {}
        except (OSError, ValueError):
            meta = {}
        thumb = d / str(meta.get("thumbnail") or "thumb.jpg")
        params = meta.get("params")
        out.append(LibraryEntry(
            name=d.name, id=str(meta.get("id") or f"lib:{d.name}"), describe=str(meta.get("describe", "")),
            layer=str(meta.get("layer", "")), params=params if isinstance(params, dict) else {},
            thumbnail=str(thumb) if thumb.is_file() else "", path=str(js),
            kits=[str(k) for k in meta.get("kits") or []], tags=[str(t) for t in meta.get("tags") or []]))
    return out


def load_beds(beds_dir: Path) -> list[Bed]:
    """Music beds from every ``beds/<style>/bars.json``."""
    out: list[Bed] = []
    if not beds_dir.is_dir():
        return out
    for bars in sorted(beds_dir.glob("*/bars.json")):
        try:
            data = json.loads(bars.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for b in data.get("beds") or []:
            if not isinstance(b, dict) or not b.get("id"):
                continue
            out.append(Bed(id=str(b["id"]), style=str(b.get("style") or data.get("style") or bars.parent.name),
                           title=str(b.get("title", "")), bpm=float(b.get("bpm") or 120.0),
                           bar_s=float(b.get("bar_s") or 240.0 / float(b.get("bpm") or 120.0)),
                           duration_s=float(b.get("duration_s") or 0.0), notes=str(b.get("notes", "")),
                           sections=[s for s in b.get("sections") or [] if isinstance(s, dict)]))
    return out


def load_sfx(sfx_json: Path) -> dict[str, dict[str, Any]]:
    """Sound names -> {class, tags, dur} from ``assets/audio/sfx/sfx.json``."""
    try:
        data = json.loads(sfx_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, s in (data.get("sounds") or {}).items():
        if isinstance(s, dict):
            files = s.get("files") or s.get("variants") or []
            dur = max((float(f.get("dur", 0)) for f in files if isinstance(f, dict)), default=0.0)
            out[str(name)] = {"class": s.get("class", ""), "tags": list(s.get("tags") or []), "dur": dur}
    return out


# ---------------------------------------------------------------------- helpers

def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _clip(text: str, n: int) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n].rsplit("\n", 1)[0] + "\n[... truncated]"


def _one_line(text: str, n: int) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _summary(doc: str) -> str:
    """First prose paragraph of a KIT.md (skips headings, code and tables)."""
    para: list[str] = []
    in_code = False
    for line in doc.splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or s.startswith(("#", "|", "<!--")):
            if para:
                break
            continue
        if not s:
            if para:
                break
            continue
        para.append(s)
    return _one_line(" ".join(para), 300)


def _describe_from_doc(doc: str, sid: str) -> str:
    """The KIT.md line(s) that mention ``sid`` (bullet or heading + following paragraph)."""
    lines = doc.splitlines()
    for i, line in enumerate(lines):
        if sid in line:
            text = line.split(sid, 1)[1].strip(" `*:-—|")
            j = i + 1
            while not text and j < len(lines) and lines[j].strip():
                text = lines[j].strip(" `*:-—|")
                j += 1
            return _one_line(text, 240)
    return ""


def _object_after(src: str, pos: int, limit: int = 20000) -> str:
    """Text of the balanced ``{...}`` that starts at/after ``pos`` (bounded; string-aware enough for kits)."""
    start = src.find("{", pos)
    if start < 0:
        return ""
    depth, i, end = 0, start, min(len(src), start + limit)
    quote = ""
    while i < end:
        c = src[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = ""
        elif c in "'\"`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    return src[start:end]


def top_level_keys(obj_src: str) -> list[str]:
    """Keys of a JS object literal ``{a: ..., 'b': ...}`` at depth 1 (strings/comments aware enough for kits)."""
    keys: list[str] = []
    depth, i, n = 0, 0, len(obj_src)
    quote = ""
    expect_key = False
    while i < n:
        c = obj_src[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = ""
            i += 1
            continue
        if obj_src.startswith("//", i):
            j = obj_src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c in "{[(":
            depth += 1
            expect_key = depth == 1 and c == "{"
        elif c in "}])":
            depth -= 1
        elif c == "," and depth == 1:
            expect_key = True
        elif expect_key and depth == 1 and not c.isspace():
            m = re.match(r"""(['"]?)([A-Za-z_$][\w$-]*)\1\s*:""", obj_src[i:])
            if m:
                keys.append(m.group(2))
                i += m.end()
            expect_key = False
            continue
        elif c in "'\"`":
            quote = c
        i += 1
    return keys


def _param_block(obj_src: str, file_src: str = "") -> str:
    """The ``params: {...}`` literal inside a scene definition (or the const it names), or ''."""
    m = re.search(r"\bparams\s*:\s*\{", obj_src)
    if m:
        return _object_after(obj_src, m.end() - 1, 6000)
    ref = re.search(r"\bparams\s*:\s*([A-Za-z_$][\w$]*)", obj_src)
    if ref and file_src:
        decl = re.search(rf"\b(?:const|let|var)\s+{re.escape(ref.group(1))}\s*=\s*\{{", file_src)
        if decl:
            return _object_after(file_src, decl.end() - 1, 6000)
    return ""
