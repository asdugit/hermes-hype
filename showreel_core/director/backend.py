"""The Director's view of the runtime: validate, lint, build a page, dry-run it and capture keyframes.

:class:`Renderer` is the protocol the engine needs (tests inject fakes). :class:`RuntimeRenderer` implements
it with the repo's film layer (``showreel_core.film``: schema / lint / page) when present and the renderer
core (``render.workers.page_session``) for dry runs and keyframes in ONE browser session.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import re
import shutil
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .types import MediaAsset


@dataclass
class ShotError:
    """A runtime problem attributed (when possible) to a shot."""
    shot: str
    t: float | None
    msg: str
    kind: str = "error"            # error | load | determinism | qa

    def __str__(self) -> str:
        at = f" at {self.t:.2f}s" if self.t is not None else ""
        return f"[{self.kind}] shot {self.shot or '?'}{at}: {self.msg}"


@dataclass
class Preview:
    """Result of one dry run (+ optional captures, and the same captures of the product-flipped mirror)."""
    ok: bool
    load_error: str = ""
    errors: list[ShotError] = field(default_factory=list)
    qa: list[dict[str, Any]] = field(default_factory=list)
    images: list[bytes] = field(default_factory=list)
    mask_images: list[bytes] = field(default_factory=list)
    seconds: float = 0.0


class Renderer(Protocol):
    """What the Director engine needs from the runtime."""

    def validate_film(self, film: dict[str, Any]) -> list[str]: ...

    def lint_scene(self, code: str, scene_id: str) -> list[str]: ...

    def build(self, film: dict[str, Any], page_dir: Path, *, scenes: dict[str, str], assets: list[MediaAsset],
              library_dir: Path | None) -> list[str]: ...

    def preview(self, page_dir: Path, *, probe_times: Sequence[float], capture_times: Sequence[float],
                size: tuple[int, int], film_size: tuple[int, int], shots: list[dict[str, Any]],
                determinism_times: Sequence[float] = (), mask_page: Path | None = None) -> Preview: ...


def write_scenes(page_dir: Path, scenes: dict[str, str]) -> None:
    """``page_dir/scenes/<name>.js`` for every custom scene (stale files removed)."""
    d = page_dir / "scenes"
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.js"):
        if old.stem not in scenes:
            old.unlink(missing_ok=True)
    for name, code in scenes.items():
        (d / f"{name}.js").write_text(code, encoding="utf-8")


def attribute(msg: str, shots: list[dict[str, Any]]) -> tuple[str, float | None]:
    """Best guess of (shot id, time) named in a runtime error message.

    Runtime messages look like ``shot boss: render t=3.200: TypeError ...`` or
    ``module scenes/boss-battle.js failed to load: SyntaxError ...``.
    """
    sid = ""
    m = re.search(r"\b(?:shot|overlay)\s+([A-Za-z0-9][\w-]*)", msg)
    if m and any(str(s.get("id")) == m.group(1) for s in shots):
        sid = m.group(1)
    if not sid:
        for s in shots:
            scene = str(s.get("scene", ""))
            name = scene.split(":", 1)[1] if ":" in scene else ""
            if scene and (scene in msg or (scene.startswith("custom:") and f"scenes/{name}.js" in msg)):
                sid = str(s["id"])
                break
    if not sid:
        for s in sorted(shots, key=lambda s: -len(str(s.get("id", "")))):
            if re.search(rf"(?<![\w-]){re.escape(str(s.get('id')))}(?![\w-])", msg):
                sid = str(s["id"])
                break
    m = re.search(r"\bt\s*[=:]\s*(\d+(?:\.\d+)?)", msg)
    return sid, float(m.group(1)) if m else None


class RuntimeRenderer:
    """Real implementation over ``showreel_core.film`` + ``showreel_core.render``.

    ``lock`` (optional) returns a context manager held around each browser launch (the dev machine's
    render slots); the plugin passes nothing.
    """

    def __init__(self, *, lock: Callable[[], contextlib.AbstractContextManager[Any]] | None = None,
                 timeout_s: float = 90.0, kits_root: Path | None = None, gpu: bool = False) -> None:
        self.lock = lock
        self.timeout_s = timeout_s
        self.gpu = gpu          # keyframes on the GPU look like the final render (software GL picks low tiers)
        self.build_kwargs: dict[str, Any] = {"kits_root": kits_root} if kits_root else {}

    # ------------------------------------------------------------------ film layer (optional modules)
    def validate_film(self, film: dict[str, Any]) -> list[str]:
        mod = _film_module("schema")
        fn = _first(mod, ("validate_film", "validate"))
        if fn is None:
            return []
        try:
            res = fn(film)
        except Exception as exc:  # noqa: BLE001 - a validator that raises is a validation error
            return [f"{type(exc).__name__}: {exc}"]
        return _as_messages(res)

    def lint_scene(self, code: str, scene_id: str) -> list[str]:
        mod = _film_module("lint")
        fn = _first(mod, ("lint_scene", "lint_source", "lint_code", "lint"))
        if fn is None:
            return []
        try:
            res = _call_kw(fn, code, scene_id=scene_id, source=code, code=code, kind="scene")
        except Exception as exc:  # noqa: BLE001
            return [f"lint failed: {type(exc).__name__}: {exc}"]
        return _as_messages(res)

    def build(self, film: dict[str, Any], page_dir: Path, *, scenes: dict[str, str], assets: list[MediaAsset],
              library_dir: Path | None) -> list[str]:
        page_dir.mkdir(parents=True, exist_ok=True)
        mod = _film_module("page")
        fn = getattr(mod, "build_job", None) if mod is not None else None
        if fn is None:
            return ["the film page builder (showreel_core.film.page) is not in this build"]
        sources: dict[str, Any] = {f"custom:{k}": v for k, v in scenes.items()}
        for sid in _lib_ids(film):
            src = Path(library_dir or "") / sid.split(":", 1)[1] / "scene.js"
            if library_dir and src.is_file():
                sources[sid] = src
        try:
            fn(film, page_dir, scenes=sources, assets=_asset_specs(film, page_dir, assets), **self.build_kwargs)
        except Exception as exc:  # noqa: BLE001 - build problems go back to the engine as errors
            issues = getattr(exc, "issues", None)
            if issues:
                return [str(i) for i in issues]
            return [f"page build failed: {type(exc).__name__}: {exc}"]
        return []

    # ------------------------------------------------------------------ dry run + keyframes
    def preview(self, page_dir: Path, *, probe_times: Sequence[float], capture_times: Sequence[float],
                size: tuple[int, int], film_size: tuple[int, int], shots: list[dict[str, Any]],
                determinism_times: Sequence[float] = (), mask_page: Path | None = None) -> Preview:
        from ..render.errors import RenderError
        from ..render.workers import _run_sync, page_session

        t_start = time.monotonic()
        dpr = size[0] / float(film_size[0])

        async def go(gpu: bool) -> Preview:
            out = Preview(ok=True)
            async with page_session(page_dir, "stage.html?lenient=1", w=size[0], h=size[1], dpr=dpr, gpu=gpu,
                                    timeout_s=self.timeout_s) as p:
                seen = 0

                async def harvest(t: float) -> None:
                    nonlocal seen
                    errs = await p.evaluate("(window.__sr && window.__sr.errors) || []") or []
                    for e in errs[seen:]:
                        sid, et = attribute(str(e), shots)
                        out.errors.append(ShotError(sid or _shot_at(shots, t), et if et is not None else t, str(e)))
                    seen = len(errs)
                    for e in p.errors:
                        if "[showreel]" in e:          # console echo of an error already in __sr.errors
                            continue
                        sid, et = attribute(e, shots)
                        out.errors.append(ShotError(sid or _shot_at(shots, t), t, e))
                    p.errors.clear()

                for t in probe_times:
                    try:
                        await p.seek(t, timeout=self.timeout_s)
                    except RenderError as e:
                        out.errors.append(ShotError(_shot_at(shots, t), t, e.message))
                        continue
                    await harvest(t)
                    qa = await p.evaluate(f"(window.__sr.qa ? window.__sr.qa({float(t)!r}) : [])") or []
                    out.qa += [dict(q, t=t) for q in qa if isinstance(q, dict) and q.get("kind") != "error"]
                for t in determinism_times:
                    await p.seek(t)
                    a = hashlib.sha1(await p.capture("png")).hexdigest()
                    await p.seek(max(0.0, t - 0.73))
                    await p.seek(t)
                    b = hashlib.sha1(await p.capture("png")).hexdigest()
                    if a != b:
                        out.errors.append(ShotError(_shot_at(shots, t), t, "render is not a pure function of t: the "
                                                    "same time drew different pixels after seeking elsewhere",
                                                    "determinism"))
                for t in capture_times:
                    await p.seek(t)
                    out.images.append(await p.capture("png"))
                    await harvest(t)
            if mask_page is not None and capture_times and not out.errors:
                async with page_session(mask_page, "stage.html?lenient=1", w=size[0], h=size[1], dpr=dpr, gpu=gpu,
                                        timeout_s=self.timeout_s) as m:
                    for t in capture_times:
                        await m.seek(t)
                        out.mask_images.append(await m.capture("png"))
            return out

        def attempt(gpu: bool) -> Preview:
            try:
                with self.lock() if self.lock else contextlib.nullcontext():
                    return _run_sync(lambda: go(gpu))
            except RenderError as e:
                detail = "; ".join(str(x) for x in (e.details.get("errors") or [])[:6]) if hasattr(e, "details") else ""
                prev = Preview(ok=False, load_error=f"{e.message}{' | ' + detail if detail else ''}")
                for msg in (getattr(e, "details", {}) or {}).get("errors") or []:
                    sid, et = attribute(str(msg), shots)
                    prev.errors.append(ShotError(sid, et, str(msg), "load"))
                return prev
            except Exception as e:  # noqa: BLE001 - any other failure is a load failure for the engine
                return Preview(ok=False, load_error=f"{type(e).__name__}: {e}")

        prev = attempt(self.gpu)
        if self.gpu and not prev.ok and not prev.errors:      # GPU launch trouble: software GL still works
            prev = attempt(False)
        prev.seconds = round(time.monotonic() - t_start, 2)
        return prev


# ------------------------------------------------------------------------- dev render slots

@contextlib.contextmanager
def render_slot(root: Path, who: str = "wp-l-director", wait_s: float = 900.0) -> Iterator[Path]:
    """Hold one of the dev machine's 3 render slot files (see render.lock.README)."""
    import os

    deadline = time.monotonic() + wait_s
    while True:
        for i in (1, 2, 3):
            p = root / f"render.slot{i}"
            try:
                if p.exists() and time.time() - p.stat().st_mtime >= 900:
                    p.unlink(missing_ok=True)
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(f"{who} {os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%S')}")
            try:
                yield p
            finally:
                p.unlink(missing_ok=True)
            return
        if time.monotonic() > deadline:
            raise TimeoutError("no free render slot")
        time.sleep(5)


# ------------------------------------------------------------------------- helpers

def _lib_ids(film: dict[str, Any]) -> set[str]:
    items = [*(film.get("shots") or []), *(film.get("overlays") or [])]
    return {str(i.get("scene")) for i in items if str(i.get("scene", "")).startswith("lib:")}


def _asset_specs(film: dict[str, Any], page_dir: Path, assets: list[MediaAsset]) -> dict[str, Any]:
    """Asset specs for build_job: reuse entries already prepared in this page dir, else prepare from source."""
    try:
        manifest = json.loads((page_dir / "assets" / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = {}
    by_name = {a.name: a for a in assets}
    out: dict[str, Any] = {}
    for name in film.get("assets") or {}:
        entry = manifest.get(name)
        rel = (entry or {}).get("path") or (entry or {}).get("pattern")
        first = rel.replace("%06d", "000001") if isinstance(rel, str) else None
        if entry and first and (page_dir / first).is_file():
            out[name] = entry
        elif name in by_name:
            a = by_name[name]
            out[name] = {"src": a.path, "poster": True, **({"cutout": a.cutout} if a.cutout else {})}
    return out


def _film_module(name: str) -> Any:
    try:
        import importlib
        return importlib.import_module(f"showreel_core.film.{name}")
    except ImportError:
        return None


def _first(mod: Any, names: tuple[str, ...]) -> Callable[..., Any] | None:
    if mod is None:
        return None
    for n in names:
        fn = getattr(mod, n, None)
        if callable(fn):
            return fn
    return None


def _call_kw(fn: Callable[..., Any], first: Any, **kwargs: Any) -> Any:
    """Call ``fn(first, **accepted_kwargs)`` passing only keywords the function declares."""
    import inspect
    params = inspect.signature(fn).parameters
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return fn(first, **kwargs)
    names = list(params)
    accepted = {k: v for k, v in kwargs.items() if k in params and (not names or k != names[0])}
    return fn(first, **accepted)


def _as_messages(res: Any) -> list[str]:
    """Normalise a validator/linter result (list of str/dict/objects, or an object with .errors) to strings."""
    if res is None or res is True:
        return []
    if hasattr(res, "errors") and not isinstance(res, (list, tuple, dict)):
        res = res.errors
    if isinstance(res, dict):
        res = res.get("errors") or []
    out = []
    for item in res if isinstance(res, (list, tuple)) else [res]:
        if isinstance(item, dict):
            if item.get("severity") in ("warning", "info"):
                continue
            out.append(" ".join(str(item.get(k)) for k in ("path", "msg", "message") if item.get(k)) or str(item))
        elif getattr(item, "severity", "error") in ("warning", "info"):
            continue
        else:
            out.append(str(item))
    return out


def _shot_at(shots: list[dict[str, Any]], t: float) -> str:
    for s in shots:
        if float(s["t0"]) <= t < float(s["t1"]):
            return str(s["id"])
    return str(shots[-1]["id"]) if shots else ""


def copy_page(src: Path, dst: Path) -> None:
    """Replace ``dst`` with a copy of the page directory ``src``."""
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)
