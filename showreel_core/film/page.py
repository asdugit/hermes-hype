"""Build a renderable job dir from a film (SDK.md §1): runtime + kits + scenes + vendor/three + assets + stage.html.

    job/stage.html  job/film.json  job/runtime/  job/kits/<kit>/  job/scenes/<name>.js
    job/assets/manifest.json  job/assets/<name>/...  job/vendor/three/ (only when THREE is used)

The page is served over loopback by ``showreel_core.render.serve.PageServer`` (ES modules need http).
"""
from __future__ import annotations

import html
import json
import posixpath
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .schema import SCENE_ID_RE, FilmIssue, errors_of, normalize_film, validate_film

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = REPO_ROOT / "runtime"
KITS_ROOT = REPO_ROOT / "kits"
VENDOR_THREE = REPO_ROOT / "vendor" / "three"

KIT_REF_RE = re.compile(r"""\b(?:ctx|sr)\.kit\(\s*['"]([a-z0-9_-]+)['"]""")
# static relative imports / re-exports: import x from './a.js', import './a.js', export { y } from '../b.js'
IMPORT_SPEC_RE = re.compile(r"""(?:\bfrom|\bimport)\s*['"](\.{1,2}/[^'"\n]+)['"]""")
THREE_RE = re.compile(r"""layer\s*:\s*['"]three['"]|from\s+['"]three(?:/addons/[^'"]*)?['"]|\bctx\.THREE\b|\bimport\(\s*['"]three""")
KIT_COPY_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.py", "tests", "demo_out", ".git*", "*.blend", "*.psd")

STAGE_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>html,body{{margin:0;padding:0;overflow:hidden;background:#000}}</style>
{importmap}</head>
<body><div id="sr-stage"></div>
<script type="module">
import {{ boot }} from './runtime/showreel.js';
boot({{ film: 'film.json', manifest: 'assets/manifest.json', modules: {modules}, fonts: {fonts} }});
</script>
</body></html>
"""
IMPORTMAP = ('<script type="importmap">{"imports": {"three": "./vendor/three/build/three.module.min.js", '
             '"three/addons/": "./vendor/three/examples/jsm/"}}</script>\n')


class JobError(Exception):
    """The film or its inputs cannot be built into a job; ``issues`` holds the precise problems."""

    def __init__(self, issues: list[FilmIssue]):
        self.issues = issues
        super().__init__("; ".join(str(i) for i in issues[:12]) + (" ..." if len(issues) > 12 else ""))

    def to_dict(self) -> dict[str, Any]:
        return {"code": "film_invalid", "message": str(self), "issues": [i.to_dict() for i in self.issues]}


def scene_filename(scene_id: str) -> str:
    """``custom:boss`` -> ``boss.js``; ``lib:flower`` -> ``lib-flower.js`` (both live in job/scenes/)."""
    kind, _, name = scene_id.partition(":")
    if kind not in ("custom", "lib") or not SCENE_ID_RE.match(scene_id):
        raise ValueError(f"not a custom:/lib: scene id: {scene_id!r}")
    return f"{name}.js" if kind == "custom" else f"lib-{name}.js"


def imported_kits(js: str, rel_path: str) -> set[str]:
    """Kits that the static relative imports of the job file ``rel_path`` land in.

    Each specifier is resolved against the importing file's own directory (``kits/pixel/scenes/a.js``
    importing ``'../core/b.js'`` stays in ``pixel``; ``scenes/x.js`` importing ``'../runtime/showreel.js'``
    is the runtime, not a kit; ``kits/pixel/kit.js`` importing ``'../nature/lib/w.js'`` is kit ``nature``).
    """
    base = posixpath.dirname(rel_path.replace("\\", "/"))
    out: set[str] = set()
    for spec in IMPORT_SPEC_RE.findall(js):
        parts = posixpath.normpath(posixpath.join(base, spec)).split("/")
        if len(parts) >= 3 and parts[0] == "kits" and re.fullmatch(r"[a-z0-9_-]+", parts[1], re.IGNORECASE):
            out.add(parts[1])
    return out


def kits_referenced(js: str, rel_path: str = "scenes/scene.js") -> set[str]:
    """Kit names a JS source refers to: ``ctx.kit('x')``, ``sr.kit('x')`` and relative imports that resolve
    into ``kits/x/`` from ``rel_path`` (the file's job-relative path; scenes live in ``scenes/``)."""
    return set(KIT_REF_RE.findall(js)) | imported_kits(js, rel_path)


def film_kits(film: Mapping[str, Any]) -> set[str]:
    """Kits a film names directly: kit: scene ids and transition types, film.kits, kits/<k>/ font paths."""
    out: set[str] = set(film.get("kits") or [])
    items = [*(film.get("shots") or []), *(film.get("overlays") or [])]
    names = [s.get("scene") for s in items if isinstance(s, Mapping)]
    names += [t.get("type") for t in film.get("transitions") or [] if isinstance(t, Mapping)]
    for n in names:
        m = re.match(r"^kit:([a-z0-9_-]+)/", str(n or ""), re.IGNORECASE)
        if m:
            out.add(m.group(1))
    for f in film.get("fonts") or []:
        m = re.match(r"^kits/([a-z0-9_-]+)/", str((f or {}).get("src", "")))
        if m:
            out.add(m.group(1))
    return out


def _js_sources(root: Path) -> list[tuple[Path, str]]:
    return [(p, p.read_text(encoding="utf-8", errors="replace")) for p in sorted(root.rglob("*.js")) if "vendor" not in p.parts[len(root.parts):]]


def _order_kits(deps: dict[str, set[str]]) -> list[str]:
    """Dependencies first (kits calling sr.kit('other') at import time need 'other' loaded first)."""
    out: list[str] = []
    seen: set[str] = set()

    def visit(k: str, stack: tuple[str, ...]) -> None:
        if k in seen or k in stack:
            return
        for d in sorted(deps.get(k, ())):
            if d != k:
                visit(d, (*stack, k))
        seen.add(k)
        out.append(k)

    for k in sorted(deps):
        visit(k, ())
    return out


def _kit_meta(kit_dir: Path, problems: list[FilmIssue]) -> dict[str, Any]:
    """kits/<k>/kit.json (optional): {"requires": ["three" | kit names], "fonts": [{family, src, weight?, style?}]}."""
    p = kit_dir / "kit.json"
    if not p.is_file():
        return {}
    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        problems.append(FilmIssue("kits", f"{kit_dir.name}/kit.json is not valid JSON: {e}"))
        return {}
    return meta if isinstance(meta, dict) else {}


def _clean(job: Path, name: str) -> None:
    p = job / name
    if p.is_dir() and p.resolve().parent == job.resolve():
        shutil.rmtree(p)


def build_job(film: Mapping[str, Any], job_dir: Path, *, kits_root: Path | None = None,
              scenes: Mapping[str, str | Path] | None = None, assets: Mapping[str, Any] | None = None,
              runtime_root: Path | None = None, vendor_three: Path | None = None, ffmpeg: str | None = None) -> Path:
    """Write a renderable job dir and return it. Raises :class:`JobError` with precise issues.

    ``scenes`` maps ``custom:``/``lib:`` scene ids to JS source text (or a Path to a .js file).
    ``assets`` maps asset names to either prepared manifest entries (``{"type": "image", "path": ...}`` /
    ``{"type": "frames", "pattern": ..., "count": ...}``, files already inside ``job_dir``) or source specs
    ``{"src": "/abs/car.mp4", ...}`` that are prepared now with :func:`showreel_core.film.assets.prepare_asset`.
    """
    kits_root = Path(kits_root) if kits_root else KITS_ROOT
    runtime_root = Path(runtime_root) if runtime_root else RUNTIME_ROOT
    vendor_three = Path(vendor_three) if vendor_three else VENDOR_THREE
    job = Path(job_dir)
    issues = errors_of(validate_film(film))
    if issues:
        raise JobError(issues)
    film_n = normalize_film(film)
    blender = [str(s.get("id")) for s in film_n["shots"] if str(s.get("scene") or "").startswith("blender:")]
    if blender:
        raise JobError([FilmIssue("shots", f"Blender shots {', '.join(blender)} must be rendered first "
                                           "(showreel_core.blender.film.render_film_shots rewrites them to kit:frames/play)")])
    scenes = dict(scenes or {})
    problems: list[FilmIssue] = []

    job.mkdir(parents=True, exist_ok=True)
    for name in ("runtime", "kits", "scenes", "vendor"):
        _clean(job, name)

    # runtime
    if not (runtime_root / "showreel.js").is_file():
        raise JobError([FilmIssue("", f"runtime not found at {runtime_root}")])
    shutil.copytree(runtime_root, job / "runtime", ignore=shutil.ignore_patterns("__pycache__", "src", "*.md", "*.py"))

    # scenes (custom:/lib:)
    used_ids = {s.get("scene") for s in [*film_n["shots"], *film_n["overlays"]]}
    used_ids |= {t.get("type") for t in film_n["transitions"]}
    for sid in sorted(i for i in used_ids if isinstance(i, str) and i.startswith(("custom:", "lib:"))):
        if sid not in scenes:
            problems.append(FilmIssue("shots", f"scene {sid!r} is used but no source was given"))
    scene_mods: list[str] = []
    scene_src: dict[str, str] = {}
    (job / "scenes").mkdir(exist_ok=True)
    for sid, src in scenes.items():
        try:
            fname = scene_filename(sid)
        except ValueError as e:
            problems.append(FilmIssue(f"scenes.{sid}", str(e)))
            continue
        text = src.read_text(encoding="utf-8") if isinstance(src, Path) else str(src)
        (job / "scenes" / fname).write_text(text, encoding="utf-8", newline="\n")
        scene_mods.append(f"scenes/{fname}")
        scene_src[sid] = text

    # kits (transitively through references in kit and scene code)
    want = film_kits(film_n)
    for sid, text in scene_src.items():
        want |= kits_referenced(text, f"scenes/{scene_filename(sid)}")
    deps: dict[str, set[str]] = {}
    kit_fonts: list[dict[str, Any]] = []
    needs_three = False
    queue = sorted(want)
    while queue:
        k = queue.pop()
        if k in deps:
            continue
        src_dir = kits_root / k
        if not (src_dir / "kit.js").is_file():
            problems.append(FilmIssue("kits", f"kit {k!r} not found ({src_dir / 'kit.js'} missing)"))
            deps[k] = set()
            continue
        shutil.copytree(src_dir, job / "kits" / k, ignore=KIT_COPY_IGNORE)
        refs: set[str] = set()
        for path, text in _js_sources(job / "kits" / k):
            refs |= kits_referenced(text, path.relative_to(job).as_posix())
        meta = _kit_meta(job / "kits" / k, problems)
        for req in meta.get("requires") or []:
            if req == "three":
                needs_three = True
            elif isinstance(req, str):
                refs.add(req)
        for f in meta.get("fonts") or []:
            if isinstance(f, Mapping) and isinstance(f.get("src"), str):
                kit_fonts.append({**f, "src": f"kits/{k}/{f['src']}"})
        deps[k] = refs - {k}
        queue.extend(sorted(deps[k]))
    kit_mods = [f"kits/{k}/kit.js" for k in _order_kits(deps) if (job / "kits" / k / "kit.js").is_file()]

    # three.js only when something uses it
    needs_three = needs_three or any(THREE_RE.search(t) for t in scene_src.values())
    if not needs_three and (job / "kits").is_dir():
        needs_three = any(THREE_RE.search(t) for _, t in _js_sources(job / "kits"))
    if needs_three:
        if not (vendor_three / "build" / "three.module.min.js").is_file():
            problems.append(FilmIssue("", f"three.js is needed but {vendor_three} is missing"))
        else:
            shutil.copytree(vendor_three, job / "vendor" / "three")

    # assets
    manifest = _assets(job, film_n, assets or {}, problems, ffmpeg)

    # fonts must exist inside the job
    for i, f in enumerate(film_n["fonts"]):
        if not (job / f["src"]).is_file():
            problems.append(FilmIssue(f"fonts[{i}].src", f"{f['src']} not found in the job (kit not copied or wrong path)"))
    for f in kit_fonts:
        if not (job / f["src"]).is_file():
            problems.append(FilmIssue("kits", f"kit font {f['src']} (kit.json) is missing"))

    if problems:
        raise JobError(problems)
    (job / "assets").mkdir(exist_ok=True)
    (job / "assets" / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    (job / "film.json").write_text(json.dumps(film_n, indent=1, ensure_ascii=False), encoding="utf-8")
    (job / "stage.html").write_text(STAGE_HTML.format(
        title=html.escape(f"{film_n.get('title') or 'Film'} · Hype"),
        importmap=IMPORTMAP if needs_three else "",
        modules=json.dumps(kit_mods + sorted(scene_mods)),
        fonts=json.dumps(kit_fonts, ensure_ascii=False),
    ), encoding="utf-8", newline="\n")
    return job


def _assets(job: Path, film: dict[str, Any], given: Mapping[str, Any], problems: list[FilmIssue],
            ffmpeg: str | None) -> dict[str, Any]:
    man_path = job / "assets" / "manifest.json"
    manifest: dict[str, Any] = {}
    if man_path.is_file():
        try:
            manifest = json.loads(man_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {}
    for name, spec in given.items():
        if not isinstance(spec, Mapping):
            problems.append(FilmIssue(f"assets.{name}", "asset spec must be an object"))
            continue
        if "src" in spec and not ("path" in spec or "pattern" in spec):
            from .assets import AssetError, prepare_asset

            try:
                manifest[name] = prepare_asset(name, spec, job, fps=float(film.get("fps", 30)), ffmpeg=ffmpeg)
            except AssetError as e:
                problems.append(FilmIssue(f"assets.{name}", str(e)))
            continue
        rel = spec.get("path") or spec.get("poster") or spec.get("pattern")
        first = rel.replace("%06d", "000001") if isinstance(rel, str) and "%" in rel else rel
        if not isinstance(first, str) or not (job / first).is_file():
            problems.append(FilmIssue(f"assets.{name}", f"prepared file {rel!r} is not inside the job dir"))
            continue
        manifest[name] = dict(spec)
    for name in film.get("assets") or {}:
        if name not in manifest:
            problems.append(FilmIssue(f"assets.{name}", "film.json names this asset but no media was given"))
    return manifest
