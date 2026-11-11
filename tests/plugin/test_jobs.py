"""Persisted job state: create/update/log, cancel flags, lookups, stale marking, pruning, concurrency."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from showreel_core.jobs import (
    JobStore,
    new_job_id,
    public_view,
    read_json,
    valid_id,
    write_json_atomic,
)


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    return JobStore(tmp_path)


def test_create_and_shape(store: JobStore) -> None:
    job = store.create("sess", {"style": "launch"}, surface="desktop")
    assert valid_id(job["id"]) and job["stage"] == "queued" and job["pid"] == os.getpid()
    loaded = store.load(job["id"])
    for key in ("id", "session_id", "created", "options", "stage", "pct", "eta_s", "error", "storyboard",
                "timeline_paths", "outputs", "contact_sheet", "log"):
        assert key in loaded
    assert (store.job_dir(job["id"]) / "job.json").is_file()


def test_ids() -> None:
    a = new_job_id(0)
    assert a.startswith("19700101-000000-") and valid_id(a)
    assert not valid_id("../etc") and not valid_id("") and not valid_id(None)


def test_bad_ids_never_touch_disk(store: JobStore) -> None:
    with pytest.raises(ValueError):
        store.job_dir("../../x")
    assert store.load("../../x") is None and not store.cancel_requested("..")


def test_update_and_log(store: JobStore) -> None:
    job = store.create("s", {})
    store.update(job["id"], stage="render", pct=0.5)
    store.log(job["id"], "hello")
    store.log(job["id"], "careful", "warn")
    j = store.load(job["id"])
    assert j["stage"] == "render" and j["pct"] == 0.5
    assert [e["msg"] for e in j["log"]] == ["hello", "careful"] and j["warnings"] == ["careful"]
    assert store.update("20000101-000000-dead", stage="x") is None


def test_log_is_capped(store: JobStore, monkeypatch: pytest.MonkeyPatch) -> None:
    import showreel_core.jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "LOG_CAP", 20)
    job = store.create("s", {})
    for i in range(25):
        store.log(job["id"], f"m{i}")
    log = store.load(job["id"])["log"]
    assert len(log) == 20 and log[0]["msg"] == "m5" and log[-1]["msg"] == "m24"
    assert len(public_view(store.load(job["id"]), 5)["log"]) == 5


def test_list_latest_find(store: JobStore) -> None:
    a = store.create("s1", {})
    b = store.create("s1", {})
    c = store.create("s2", {})
    assert [j["id"] for j in store.list("s1")] == [b["id"], a["id"]]
    assert store.latest("s1")["id"] == b["id"] and store.latest("nope") is None
    assert store.find("", "s2")["id"] == c["id"]
    assert store.find(a["id"])["id"] == a["id"]
    assert store.find(b["id"][-4:], "s1")["id"] == b["id"]


def test_cancel_flag(store: JobStore) -> None:
    job = store.create("s", {})
    assert not store.cancel_requested(job["id"])
    assert store.request_cancel(job["id"]) and store.cancel_requested(job["id"])
    store.update(job["id"], stage="done")
    other = store.create("s", {})
    store.update(other["id"], stage="done")
    assert not store.request_cancel(other["id"])            # finished jobs cannot be cancelled


def test_storyboard_edits(store: JobStore) -> None:
    job = store.create("s", {})
    assert store.storyboard_edit(job["id"]) is None
    store.save_storyboard_edit(job["id"], {"scenes": [{"type": "TITLE"}]})
    assert store.storyboard_edit(job["id"]) == {"scenes": [{"type": "TITLE"}]}


def test_mark_stale(store: JobStore) -> None:
    now = time.time()
    live = store.create("s", {})
    orphan = store.create("s", {})
    dead = store.create("s", {})
    store.update(dead["id"], pid=2 ** 30)                  # no such process
    fresh = store.create("s", {})
    store.update(fresh["id"], pid=2 ** 30)
    for j in (live, orphan, dead):
        path = store.job_dir(j["id"]) / "job.json"
        data = read_json(path)
        data["updated"] = now - 120
        write_json_atomic(path, data)
    marked = store.mark_stale(now=now, active_ids={live["id"]})
    assert set(marked) == {orphan["id"], dead["id"]}
    assert store.load(orphan["id"])["error"]["code"] == "interrupted"
    assert store.load(live["id"])["stage"] == "queued" and store.load(fresh["id"])["stage"] == "queued"


def test_prune_keeps_running_and_newest(store: JobStore) -> None:
    jobs = []
    for _ in range(5):
        j = store.create("s", {})
        store.update(j["id"], stage="done")
        jobs.append(j)
    running = store.create("s", {})
    old = jobs[0]
    path = store.job_dir(old["id"]) / "job.json"
    data = read_json(path)
    data["created"] = time.time() - 30 * 86400
    write_json_atomic(path, data)
    removed = store.prune(keep=3, max_age_days=14)
    assert old["id"] in removed and len(removed) == 2
    assert store.load(running["id"]) is not None


def test_prune_work(store: JobStore) -> None:
    job = store.create("s", {})
    d = store.job_dir(job["id"])
    (d / "chunks_16x9").mkdir()
    (d / "chunks_16x9" / "c0.mp4").write_bytes(b"x")
    (d / "mix_16x9").mkdir()
    (d / "mix_16x9" / "mix_stem_voice.wav").write_bytes(b"x")
    (d / "auteur_16x9.mp4").write_bytes(b"x")
    store.prune_work(job["id"])
    assert not (d / "chunks_16x9").exists() and not (d / "mix_16x9" / "mix_stem_voice.wav").exists()
    assert (d / "auteur_16x9.mp4").exists()


def test_concurrent_logs_and_reads_never_corrupt(store: JobStore) -> None:
    job = store.create("s", {})
    errors: list[BaseException] = []

    def writer(k: int) -> None:
        try:
            for i in range(25):
                store.log(job["id"], f"w{k}-{i}")
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    def reader() -> None:
        for _ in range(100):
            if store.load(job["id"]) is None:
                errors.append(AssertionError("unreadable"))

    threads = [threading.Thread(target=writer, args=(k,)) for k in range(4)] + [threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(store.load(job["id"])["log"]) == 100


def test_done_text_says_why_the_storyboard_is_built_in() -> None:
    from showreel_core.deliver import done_text
    base = {"id": "j1", "stage": "done", "title": "Tempo", "duration_s": 30.0, "storyboard_source": "heuristic",
            "delivered": {"16:9": "/v/a.mp4"}}
    failed = done_text({**base, "warnings": ["the model's storyboard was unusable; used the heuristic storyboard"]},
                       media=True)
    assert "could not be used" in failed and "unavailable" not in failed
    assert "none was available" in done_text({**base, "warnings": []}, media=True)
