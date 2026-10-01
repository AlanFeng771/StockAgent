"""手動觸發的分析工作管理（全清單在背景執行、同時只允許一個分析）。

規格（Stage 7 spec，2026-10-01 使用者確認：全清單背景執行 + 防重複執行）
======================================================================

``AnalysisJobManager(run_in_background=_thread_runner)``

- ``start_watchlist_job(stock_ids, analyze_and_save) -> JobStatus``：
  已有分析在執行 → ``AnalysisBusyError``；否則建立工作並交給 ``run_in_background`` 執行，立刻回傳狀態。
  逐檔呼叫 ``analyze_and_save(stock_id)``；單檔失敗（任何例外）只記錄在 ``failed``，不中斷其他股票
- ``run_single(stock_id, analyze_and_save)``：單檔同步執行，與全清單共用同一把鎖
  （避免同時重複分析、重複花費 OpenAI 額度）；忙碌中 → ``AnalysisBusyError``
- ``status() -> JobStatus``：最近一次全清單工作的狀態；從未執行 → state = idle
- ``run_in_background``：預設開新執行緒；測試注入「立刻同步執行」的 runner

``JobStatus``：state（idle / running / done）、total、completed（含失敗）、succeeded（股票代號）、
failed（[{stock_id, error}]）、started_at、finished_at
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Callable, Literal

from pydantic import BaseModel


class AnalysisBusyError(Exception):
    """已有分析在執行。"""


class FailedStock(BaseModel):
    stock_id: str
    error: str


class JobStatus(BaseModel):
    state: Literal["idle", "running", "done"]
    total: int = 0
    completed: int = 0
    succeeded: list[str] = []
    failed: list[FailedStock] = []
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _thread_runner(target: Callable[[], None]) -> None:
    threading.Thread(target=target, daemon=True, name="analysis-job").start()


class AnalysisJobManager:
    def __init__(self, run_in_background: Callable[[Callable[[], None]], None] = _thread_runner) -> None:
        self._run_in_background = run_in_background
        self._lock = threading.Lock()
        self._status = JobStatus(state="idle")

    def status(self) -> JobStatus:
        return self._status.model_copy(deep=True)

    def start_watchlist_job(self, stock_ids: list[str], analyze_and_save: Callable[[str], object]) -> JobStatus:
        if not self._lock.acquire(blocking=False):
            raise AnalysisBusyError("已有分析在執行中")
        self._status = JobStatus(state="running", total=len(stock_ids), started_at=datetime.now())

        def work() -> None:
            try:
                for stock_id in stock_ids:
                    try:
                        analyze_and_save(stock_id)
                        self._status.succeeded.append(stock_id)
                    except Exception as exc:  # 單檔失敗不中斷其他股票
                        self._status.failed.append(FailedStock(stock_id=stock_id, error=f"{type(exc).__name__}: {exc}"))
                    self._status.completed += 1
            finally:
                self._status.state = "done"
                self._status.finished_at = datetime.now()
                self._lock.release()

        try:
            self._run_in_background(work)
        except Exception:
            self._status = JobStatus(state="idle")
            self._lock.release()
            raise
        return self.status()

    def run_single(self, stock_id: str, analyze_and_save: Callable[[str], object]):
        if not self._lock.acquire(blocking=False):
            raise AnalysisBusyError("已有分析在執行中")
        try:
            return analyze_and_save(stock_id)
        finally:
            self._lock.release()
