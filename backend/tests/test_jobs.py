from __future__ import annotations

import pytest

from backend.app.pipeline.jobs import AnalysisBusyError, AnalysisJobManager


def run_now(target):
    target()


class Deferred:
    """先不執行，讓測試能觀察「執行中」狀態。"""

    def __init__(self):
        self.target = None

    def __call__(self, target):
        self.target = target


def test_initial_status_idle():
    assert AnalysisJobManager(run_now).status().state == "idle"


def test_watchlist_job_runs_each_stock_and_records_failures():
    calls = []

    def analyze(stock_id):
        calls.append(stock_id)
        if stock_id == "2454":
            raise RuntimeError("FinMind 402")

    manager = AnalysisJobManager(run_now)
    manager.start_watchlist_job(["2330", "2454", "0056"], analyze)
    status = manager.status()

    assert calls == ["2330", "2454", "0056"]
    assert status.state == "done"
    assert (status.total, status.completed) == (3, 3)
    assert status.succeeded == ["2330", "0056"]
    assert [(f.stock_id, f.error) for f in status.failed] == [("2454", "RuntimeError: FinMind 402")]
    assert status.started_at is not None and status.finished_at is not None


def test_start_returns_running_status_immediately():
    runner = Deferred()
    manager = AnalysisJobManager(runner)

    started = manager.start_watchlist_job(["2330"], lambda s: None)

    assert started.state == "running"
    assert manager.status().completed == 0
    runner.target()
    assert manager.status().state == "done"


def test_second_job_while_running_is_rejected():
    runner = Deferred()
    manager = AnalysisJobManager(runner)
    manager.start_watchlist_job(["2330"], lambda s: None)

    with pytest.raises(AnalysisBusyError):
        manager.start_watchlist_job(["2454"], lambda s: None)
    with pytest.raises(AnalysisBusyError):
        manager.run_single("2454", lambda s: None)

    runner.target()
    manager.start_watchlist_job(["2454"], lambda s: None)  # 結束後可再執行


def test_run_single_returns_value_and_releases_lock_on_error():
    manager = AnalysisJobManager(run_now)

    assert manager.run_single("2330", lambda s: f"ok {s}") == "ok 2330"
    with pytest.raises(ValueError):
        manager.run_single("2330", lambda s: (_ for _ in ()).throw(ValueError("x")))
    assert manager.run_single("2330", lambda s: "again") == "again"


def test_lock_released_even_if_runner_fails_to_start():
    def broken_runner(target):
        raise RuntimeError("cannot start thread")

    manager = AnalysisJobManager(broken_runner)
    with pytest.raises(RuntimeError):
        manager.start_watchlist_job(["2330"], lambda s: None)

    assert manager.run_single("2330", lambda s: "ok") == "ok"
