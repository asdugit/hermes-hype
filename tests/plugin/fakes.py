"""A stand-in for Hermes' PluginContext that records registrations (signatures match hermes_cli.plugins)."""
from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


class FakeHandle:
    def __init__(self, text: str) -> None:
        self.ok = True
        self.texts = [text]

    def edit(self, text: str) -> None:
        self.texts.append(text)


class FakeCtx:
    def __init__(self, *, surface: str = "cli", config: dict[str, Any] | None = None,
                 tts: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> None:
        self.surface = surface
        self.config = dict(config or {})
        self.commands: dict[str, dict[str, Any]] = {}
        self.tools: dict[str, dict[str, Any]] = {}
        self.cli: dict[str, dict[str, Any]] = {}
        self.aux: dict[str, dict[str, Any]] = {}
        self.skills: dict[str, dict[str, Any]] = {}
        self.unload: list[Callable[[], None]] = []
        self.posted: list[FakeHandle] = []
        self.dispatched: list[tuple[str, dict[str, Any]]] = []
        self.tts = tts
        self.llm = None

    # registrars
    def register_command(self, name: str, handler: Callable, description: str = "", args_hint: str = "",
                         argument_mode: str | None = None) -> None:
        self.commands[name] = {"handler": handler, "description": description, "args_hint": args_hint,
                               "argument_mode": argument_mode}

    def register_tool(self, name: str, toolset: str, schema: dict, handler: Callable, check_fn: Callable | None = None,
                      requires_env: list | None = None, is_async: bool = False, description: str = "",
                      emoji: str = "", override: bool = False) -> None:
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, "description": description}

    def register_cli_command(self, name: str, help: str, setup_fn: Callable, handler_fn: Callable | None = None,
                             description: str = "") -> None:
        self.cli[name] = {"help": help, "setup_fn": setup_fn, "handler_fn": handler_fn}

    def register_auxiliary_task(self, key: str, *, display_name: str, description: str,
                                defaults: dict | None = None, inherit_from: str | None = None) -> None:
        self.aux[key] = {"display_name": display_name, "defaults": defaults}

    def register_skill(self, name: str, path: Path, description: str = "", frontmatter: dict | None = None) -> None:
        self.skills[name] = {"path": Path(path), "description": description}

    def on_unload(self, callback: Callable[[], None]) -> None:
        self.unload.append(callback)

    # services
    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)

    def session_surface(self) -> str:
        return self.surface

    def post_message(self, text: str) -> FakeHandle:
        h = FakeHandle(text)
        self.posted.append(h)
        return h

    def dispatch_tool(self, name: str, args: dict[str, Any], **kwargs: Any) -> str:
        self.dispatched.append((name, args))
        if self.tts is None:
            return json.dumps({"success": False, "error": "no tts"})
        return json.dumps(self.tts(args))


def load_plugin(name: str = "auteur_plugin_under_test") -> Any:
    """Import the repo root as Hermes does (a package whose __init__ has register())."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod
