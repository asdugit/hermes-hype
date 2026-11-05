"""Story stage: session events -> storyboard (LLM or heuristic) -> beat-grid timeline.

Pure stdlib (Pillow is imported lazily for image focus regions). Entry points:

- :func:`generate_storyboard` - one structured LLM call, one repair call, heuristic fallback.
- :func:`build_heuristic_storyboard` - deterministic storyboard without any model.
- :func:`validate_storyboard` / :func:`validate_schema` - semantic and schema checks.
- :func:`solve_timeline` - durations on the bpm grid plus verbatim scene data, cues and splits.
"""
from __future__ import annotations

from .generate import GenerationResult, LlmReply, generate_storyboard, generate_storyboard_report, hermes_llm
from .heuristic import build_heuristic_storyboard, infer_product
from .options import StoryOptions
from .schema import STORYBOARD_SCHEMA, storyboard_from_json, storyboard_to_json, transport_schema, validate_schema
from .timing import solve_timeline
from .validate import ValidationResult, validate_storyboard

__all__ = [
    "GenerationResult", "LlmReply", "STORYBOARD_SCHEMA", "StoryOptions", "ValidationResult",
    "build_heuristic_storyboard", "generate_storyboard", "generate_storyboard_report", "hermes_llm",
    "infer_product", "solve_timeline", "storyboard_from_json", "storyboard_to_json", "transport_schema",
    "validate_schema", "validate_storyboard",
]
