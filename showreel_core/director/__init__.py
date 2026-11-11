"""Hype Director Engine: free-text direction -> a bespoke film.json with custom scenes, quality-locked by
validation, dry runs, a vision critic and revision rounds (see STUDIO.md and SDK.md).

Entry points: :func:`run` and :func:`revise` (never raise; return :class:`DirectorResult`).
Model access: :func:`hermes_llm` wraps ``ctx.llm``; :func:`hermes_cli_llm` is the dev route.
"""
from __future__ import annotations

from .backend import Preview, Renderer, RuntimeRenderer, ShotError
from .catalog import Catalog, build_catalog
from .engine import brief_from_kwargs, guess_style, revise, run
from .llm import CallLedger, DirectorLlm, Image, LlmReply, hermes_cli_llm, hermes_llm
from .media import assets_from_bundle, probe_asset
from .types import EFFORTS, Brief, Budget, Capabilities, DirectorResult, MediaAsset, RoundScore

__all__ = [
    "EFFORTS", "Brief", "Budget", "CallLedger", "Capabilities", "Catalog", "DirectorLlm", "DirectorResult", "Image",
    "LlmReply", "MediaAsset", "Preview", "Renderer", "RoundScore", "RuntimeRenderer", "ShotError",
    "assets_from_bundle", "brief_from_kwargs", "build_catalog", "guess_style", "hermes_cli_llm", "hermes_llm",
    "probe_asset", "revise", "run",
]
