"""Model calls ride out rate limits / overload / 5xx with bounded, jittered, Retry-After-aware retries (E3), and the
user is told the truth when the model could not be reached (E3/E6/E8 of the e2e audit)."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from showreel_core import llm as L
from showreel_core.llm import (
    CallTally,
    Host,
    JsonModeLlm,
    call_with_retries,
    failure_reason,
    retry_after_s,
    transient_kind,
)


class RateLimitError(Exception):
    def __init__(self, msg: str = "Error code: 429 - {'type': 'error', 'error': {'type': 'rate_limit_error'}, "
                                  "'request_id': 'req_011Cgw'}", retry_after: str | None = None) -> None:
        super().__init__(msg)
        self.status_code = 429
        self.response = SimpleNamespace(status_code=429,
                                        headers={"retry-after": retry_after} if retry_after is not None else {})


class BadRequestError(Exception):
    status_code = 400


class Flaky:
    """Fails ``n`` times with ``exc`` then answers."""

    def __init__(self, n: int, exc: Exception) -> None:
        self.n, self.exc, self.calls = n, exc, 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.n:
            raise self.exc
        return "ok"


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record waits instead of sleeping; no jitter so the numbers are exact."""
    waits: list[float] = []
    monkeypatch.setattr(L.random, "uniform", lambda a, b: 1.0 if (a, b) == (0.75, 1.25) else 0.0)
    return waits


def _sleep(waits: list[float]) -> Any:
    return lambda s: waits.append(s)


def test_kinds_of_failure() -> None:
    assert transient_kind(RateLimitError()) == "rate_limit"
    assert transient_kind(Exception("credentials are rate-limited for claude-fable-5-2")) == "rate_limit"
    assert transient_kind(Exception("Error code: 529 - overloaded_error")) == "overloaded"
    assert transient_kind(Exception("Error code: 503 - service unavailable")) == "overloaded"
    assert transient_kind(Exception("Error code: 500 - internal server error")) == "server"
    assert transient_kind(TimeoutError("read timed out")) == "timeout"
    assert transient_kind(BadRequestError("Error code: 400 - schema too complex")) == ""
    assert transient_kind(Exception("Error code: 429 - insufficient credits")) == ""     # billing: retry won't help
    assert transient_kind(Exception("401 unauthorized")) == ""


def test_retry_after_is_read_from_headers_and_text() -> None:
    assert retry_after_s(RateLimitError(retry_after="7")) == 7.0
    assert retry_after_s(Exception("rate limited, try again in 2.5s")) == 2.5
    assert retry_after_s(RateLimitError()) is None


def test_a_429_is_retried_after_a_backoff_then_succeeds(slept: list[float]) -> None:
    fn, tally = Flaky(2, RateLimitError()), CallTally()
    assert call_with_retries(fn, tally=tally, sleep=_sleep(slept)) == "ok"
    assert fn.calls == 3
    assert round(sum(slept), 2) == L.RETRY_DELAYS_S[0] + L.RETRY_DELAYS_S[1]     # 4 s then 12 s, not 0.1 s
    assert tally.snapshot()["retries"] == 2 and tally.ok == 1 and tally.failed == 0


def test_retry_after_from_the_provider_wins_when_longer(slept: list[float]) -> None:
    fn = Flaky(1, RateLimitError(retry_after="20"))
    call_with_retries(fn, sleep=_sleep(slept))
    assert 20.0 <= sum(slept) <= 21.0


def test_retries_are_bounded_in_count_and_time(slept: list[float]) -> None:
    fn, tally = Flaky(99, RateLimitError()), CallTally()
    with pytest.raises(RateLimitError):
        call_with_retries(fn, tally=tally, sleep=_sleep(slept))
    assert fn.calls <= 1 + len(L.RETRY_DELAYS_S)
    assert sum(slept) <= L.RETRY_BUDGET_S
    assert tally.failed == 1 and tally.kinds == {"rate_limit": 1}


def test_a_retry_after_longer_than_the_budget_is_not_waited_out(slept: list[float]) -> None:
    fn = Flaky(99, RateLimitError(retry_after="3600"))           # "resets in 1 hour": give up now, honestly
    with pytest.raises(RateLimitError):
        call_with_retries(fn, sleep=_sleep(slept))
    assert fn.calls == 1 and slept == []


def test_after_a_call_used_up_its_retries_the_next_ones_fail_fast(slept: list[float]) -> None:
    tally = CallTally()
    with pytest.raises(RateLimitError):
        call_with_retries(Flaky(99, RateLimitError()), tally=tally, sleep=_sleep(slept))
    waited = sum(slept)
    second = Flaky(99, RateLimitError())
    with pytest.raises(RateLimitError):
        call_with_retries(second, tally=tally, sleep=_sleep(slept))
    assert second.calls == 1 and sum(slept) == waited           # a dead provider costs the job ~1 min, not 1/call


def test_non_transient_errors_and_spent_timeouts_are_not_retried(slept: list[float]) -> None:
    bad = Flaky(1, BadRequestError("Error code: 400"))
    with pytest.raises(BadRequestError):
        call_with_retries(bad, sleep=_sleep(slept))
    slow = Flaky(1, TimeoutError("timed out"))
    with pytest.raises(TimeoutError):
        call_with_retries(slow, timeout=None, sleep=_sleep(slept))       # no known limit: never doubled
    assert bad.calls == 1 and slow.calls == 1 and slept == []


def test_cancel_ends_a_retry_wait_at_once(slept: list[float]) -> None:
    fn = Flaky(99, RateLimitError())
    with pytest.raises(RateLimitError):
        call_with_retries(fn, stop=lambda: True, sleep=_sleep(slept))
    assert fn.calls == 1 and slept == []


class LimitedLlm:
    def __init__(self, fails: int) -> None:
        self.fails, self.calls = fails, 0

    def complete_structured(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self.calls <= self.fails:
            raise RateLimitError()
        return SimpleNamespace(text='{"title": "T"}', parsed={"title": "T"}, content_type="json", provider="p",
                               model="m", usage=None)


def test_json_mode_route_retries_and_counts_on_the_hosts_tally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(JsonModeLlm, "plain_only", False)
    monkeypatch.setattr(L, "RETRY_DELAYS_S", (0.01, 0.01, 0.01))
    inner = LimitedLlm(fails=1)
    host = Host(llm=inner)
    reply = host.story_call()(instructions="I", input_text="d", json_schema={"type": "object"}, schema_name="s",
                              temperature=0.3, max_tokens=50, timeout=30)
    assert not reply.error and inner.calls == 2
    assert host.calls.ok == 1 and host.calls.retries == 1


def test_failure_reason_words() -> None:
    assert failure_reason({"kinds": {"rate_limit": 2}}) == "the model was rate-limited"
    assert failure_reason({"kinds": {"other": 1}}) == ""


def test_customize_note_has_no_raw_provider_error() -> None:
    from showreel_core.customize.hook import customize_failure_note
    note = customize_failure_note("RateLimitError: Error code: 429 - {'type': 'error', 'request_id': 'req_011Cgw'}")
    assert "rate-limited" in note and "req_" not in note and "{" not in note
    assert "rate-limited" not in customize_failure_note("no JSON object in the reply")
