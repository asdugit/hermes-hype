"""Test-summary parsing and Stats computation."""
from session_synth import PYTEST_FAIL, PYTEST_PASS, coding_session

from showreel_core.session import compute_stats, extract_events, parse_test_summary
from showreel_core.session.stats import active_duration


def test_pytest_variants():
    assert parse_test_summary(PYTEST_PASS) == {"framework": "pytest", "passed": 12, "failed": 0}
    assert parse_test_summary(PYTEST_FAIL) == {"framework": "pytest", "passed": 10, "failed": 2}
    assert parse_test_summary("3 passed, 1 warning in 0.01s")["passed"] == 3
    assert parse_test_summary("== 1 failed, 4 passed, 2 errors in 3.10s ==")["failed"] == 3


def test_last_summary_wins():
    s = parse_test_summary(PYTEST_FAIL + "\n...\n" + PYTEST_PASS)
    assert s["failed"] == 0 and s["passed"] == 12


def test_jest_vitest_cargo_go_unittest():
    assert parse_test_summary("Tests:       1 failed, 41 passed, 42 total") == {"framework": "jest", "passed": 41, "failed": 1}
    assert parse_test_summary(" Test Files  3 passed (3)\n      Tests  27 passed (27)")["passed"] == 27
    cargo = "test result: ok. 5 passed; 0 failed; 0 ignored\n\ntest result: ok. 2 passed; 0 failed; 0 ignored"
    assert parse_test_summary(cargo) == {"framework": "cargo", "passed": 7, "failed": 0}
    gov = "=== RUN   TestA\n--- PASS: TestA (0.00s)\n--- PASS: TestB (0.00s)\nok  \texample.com/x\t0.01s"
    assert parse_test_summary(gov) == {"framework": "go", "passed": 2, "failed": 0}
    goq = "ok  \texample.com/x\t0.01s\nFAIL\texample.com/y\t0.02s"
    assert parse_test_summary(goq)["unit"] == "packages"
    ut = "....\n----------------------------------------------------------------------\nRan 4 tests in 0.001s\n\nOK"
    assert parse_test_summary(ut) == {"framework": "unittest", "passed": 4, "failed": 0}


def test_no_summary():
    assert parse_test_summary("hello world\n3 passengers boarded") is None
    assert parse_test_summary("") is None


def test_active_duration_ignores_idle_gaps():
    assert active_duration([0, 10, 20, 5000, 5010]) == 30.0
    assert active_duration([None, 5.0]) == 0.0


def test_compute_stats_on_coding_session():
    rows = coding_session()
    res = extract_events(rows)
    st = compute_stats(res.events, rows, {"model": "test-model"})
    assert st.turns == 1
    assert st.tool_calls == 7
    assert st.tool_kinds["terminal"] == 2
    assert st.files_created == 1 and st.files_modified == 0
    assert st.lines_added == 9 + 2 and st.lines_removed == 1
    assert st.commands_run == 2
    assert st.commands_failed_then_fixed == 1
    assert st.tests_passed == 12
    assert st.model == "test-model"
    assert st.duration_s > 0
