"""Hype: turn what you built in this Hermes session into a narrated launch trailer.

Hermes imports this folder as a package and calls :func:`register`. Registration is cheap: the
handlers module only pulls in stdlib-level code; the session reader, storyboard, renderer and audio
stack load when a film is made.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

PLUGIN = "hype"
TOOLSET = "hype"
#: Must equal ``provides_tools`` / ``provides_hooks`` in plugin.yaml (tests/plugin checks the parity).
TOOLS = ("hype_render", "hype_status")
HOOKS: tuple[str, ...] = ()


def register(ctx, **_kwargs):  # Hermes plugin entry point (ctx: hermes_cli.plugins.PluginContext)
    """Register the aux LLM task, ``/hype``, the agent tools, the CLI, the bundled skill and unload."""
    from .showreel_core import handlers as h

    try:
        ctx.register_auxiliary_task(
            "hype", display_name="Hype storyboard",
            description="Writes the scene list, on-screen labels and narration for /hype films.",
            defaults={"timeout": 120})
    except Exception as exc:  # noqa: BLE001 - re-registration on reload / older hosts: keep the main model
        log.debug("hype: auxiliary task not registered: %s", exc)

    ctx.register_command(
        "hype", h.make_slash_handler(ctx),
        description="Make a narrated launch trailer of what this session built",
        args_hint="[lore|speedrun] [style] [30|60|90] [vertical|both] [mute] | <any direction>",
        argument_mode="text")

    ctx.register_tool(name="hype_render", toolset=TOOLSET, schema=h.RENDER_SCHEMA,
                      handler=lambda args, **kw: h.render_tool(ctx, args, **kw),
                      description=h.RENDER_SCHEMA["description"], emoji="🎬")
    ctx.register_tool(name="hype_status", toolset=TOOLSET, schema=h.STATUS_SCHEMA,
                      handler=lambda args, **kw: h.status_tool(ctx, args, **kw),
                      description=h.STATUS_SCHEMA["description"], emoji="🎬")

    try:
        ctx.register_cli_command("hype", help="Make Hype films from the command line",
                                 setup_fn=h.cli_setup, handler_fn=h.make_cli_handler(ctx),
                                 description="hermes hype render|styles|doctor|status|install-blender")
    except Exception as exc:  # noqa: BLE001 - CLI is optional
        log.debug("hype: CLI command not registered: %s", exc)

    register_skill = getattr(ctx, "register_skill", None)
    if callable(register_skill) and h.skill_path().is_file():
        try:
            register_skill("hype", h.skill_path(),
                           description="When and how to make a Hype film with hype_render.")
        except Exception as exc:  # noqa: BLE001
            log.debug("hype: skill not registered: %s", exc)

    ctx.on_unload(h.on_unload)
