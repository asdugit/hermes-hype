"""The Director must work when Hermes installs the plugin, not only from a checkout.

Hermes imports a directory plugin as ``hermes_plugins.<slug>`` (spec_from_file_location with
submodule_search_locations), so ``showreel_core`` is ``hermes_plugins.hype.showreel_core`` there and an absolute
``import showreel_core.film.page`` fails. That failure used to be reported as "the film page builder is not in this
build" and killed a real Directed job. This test copies the repo into a temp ``plugins/hype`` dir, imports it the
way the Hermes loader does, in a fresh interpreter whose sys.path does NOT contain the checkout, and checks that the
Director's backend resolves every film-layer module.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
_SKIP = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "node_modules", "tests", "docs", "assets",
                               ".pytest_cache", ".ruff_cache", "*.mp4", "*.ogg", "*.wav", "*.png", "*.jpg")


def test_director_backend_imports_film_layer_from_the_installed_layout(tmp_path: Path) -> None:
    plugin = tmp_path / "plugins" / "hype"
    shutil.copytree(REPO, plugin, ignore=_SKIP)
    probe = textwrap.dedent(f"""
        import importlib, importlib.util, json, sys, types
        from pathlib import Path
        sys.path = [p for p in sys.path if Path(p or '.').resolve() != Path({str(REPO)!r}).resolve()]
        assert importlib.util.find_spec('showreel_core') is None, 'checkout leaked into sys.path'
        plugin_dir = Path({str(plugin)!r})
        ns = types.ModuleType('hermes_plugins'); ns.__path__ = []; ns.__package__ = 'hermes_plugins'
        sys.modules['hermes_plugins'] = ns
        spec = importlib.util.spec_from_file_location('hermes_plugins.hype', plugin_dir / '__init__.py',
                                                      submodule_search_locations=[str(plugin_dir)])
        mod = importlib.util.module_from_spec(spec); mod.__package__ = 'hermes_plugins.hype'
        mod.__path__ = [str(plugin_dir)]; sys.modules['hermes_plugins.hype'] = mod
        spec.loader.exec_module(mod)
        be = importlib.import_module('hermes_plugins.hype.showreel_core.director.backend')
        out = {{'pkg': be._FILM_PKG}}
        for name in ('page', 'schema', 'lint'):
            m = be._film_module(name)
            out[name] = (m.__name__ if m else None, be.FILM_IMPORT_ERRORS.get(name))
        print(json.dumps(out))
    """)
    run = subprocess.run([sys.executable, "-c", probe], cwd=tmp_path, capture_output=True, text=True, timeout=120, check=False)
    assert run.returncode == 0, run.stderr[-2000:]
    out = json.loads(run.stdout.strip().splitlines()[-1])
    assert out["pkg"] == "hermes_plugins.hype.showreel_core.film"
    for name in ("page", "schema", "lint"):
        assert out[name] == [f"hermes_plugins.hype.showreel_core.film.{name}", None], out


def test_page_build_failure_names_the_real_import_error(monkeypatch, tmp_path: Path) -> None:
    from showreel_core.director import backend as be

    def boom(name: str):
        be.FILM_IMPORT_ERRORS[name] = "ModuleNotFoundError: No module named 'x'"

    monkeypatch.setattr(be, "_film_module", boom)
    rb = be.RuntimeRenderer.__new__(be.RuntimeRenderer)
    errs = rb.build({"shots": []}, tmp_path / "page", scenes={}, assets=[], library_dir=None)
    assert errs and "No module named 'x'" in errs[0] and "could not be loaded" in errs[0]
