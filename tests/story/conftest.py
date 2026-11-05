"""Shared fixtures for story-stage tests (synthetic sessions only)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from story_synth import SESSIONS

from showreel_core.story.facts import SessionFacts


@pytest.fixture(params=sorted(SESSIONS))
def session(request: pytest.FixtureRequest):
    """(name, events, stats) for every synthetic session."""
    events, stats = SESSIONS[request.param]()
    return request.param, events, stats


@pytest.fixture
def coding():
    """The coding session (CLI + HTML report, product captures, a failing then passing test run)."""
    return SESSIONS["coding"]()


@pytest.fixture
def coding_facts(coding):
    events, stats = coding
    return SessionFacts(events, stats)
