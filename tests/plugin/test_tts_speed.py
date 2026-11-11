"""Narration pace: the per-call TTS speed precedence check and the dev edge-tts route mapping."""
from __future__ import annotations

from showreel_core.llm import Host, edge_tts_problem, tts_provider, tts_speed_conflict


def test_no_conflict_without_provider_speed() -> None:
    assert tts_speed_conflict(1.13, {}) is None                                  # default provider edge
    assert tts_speed_conflict(1.13, {"provider": "edge", "speed": 1.0}) is None    # top-level speed is overridden
    assert tts_speed_conflict(1.13, {"provider": "edge", "edge": {"voice": "x"}}) is None
    assert tts_speed_conflict(1.0, {"provider": "edge", "edge": {"speed": 0.9}}) is None   # nothing requested


def test_provider_section_speed_wins_over_the_call() -> None:
    msg = tts_speed_conflict(1.13, {"provider": "edge", "edge": {"speed": 1.0}})
    assert msg and "tts.edge.speed=1.0" in msg and "x1.13" in msg and "remove tts.edge.speed" in msg
    assert tts_speed_conflict(1.13, {"provider": "openai", "openai": {"speed": 1.2}})


def test_providers_without_call_speed() -> None:
    assert "ignores per-call speed" in (tts_speed_conflict(1.13, {"provider": "minimax"}) or "")


def test_unreadable_config_reports_nothing() -> None:
    assert tts_speed_conflict(1.13, "garbage") is None  # type: ignore[arg-type]


def test_host_without_services_has_no_story_route() -> None:
    assert Host().story_call() is None
    Host().emit("job.progress", {})          # no broadcaster: silently ignored


def test_old_edge_tts_is_named_as_the_reason_for_captions_only() -> None:
    msg = edge_tts_problem("edge", "7.2.7")
    assert msg and "7.2.7" in msg and "403" in msg and "captions-only" in msg
    assert edge_tts_problem("edge", "7.3.1") is None
    assert edge_tts_problem("edge", "8.0") is None
    assert edge_tts_problem("openai", "7.2.7") is None          # another provider: edge-tts is irrelevant
    assert edge_tts_problem("edge", "weird") is None


def test_tts_provider_reads_the_section() -> None:
    assert tts_provider({}) == "edge" and tts_provider({"provider": "OpenAI"}) == "openai"
    assert tts_provider("garbage") == "edge"  # type: ignore[arg-type]
