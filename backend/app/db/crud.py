"""資料存取函式。每個寫入函式自行 commit。

規格（Stage 5 spec，2026-10-01 使用者確認四項行為）
================================================

股票代號
--------
``normalize_stock_id(stock_id)``：去前後空白、轉大寫；需符合「4~6 位數字＋可選 1 個英文字母」
（例：2330、0056、00981A、01001T），否則 ``InvalidStockIdError``。所有 watchlist / report 函式都先正規化，
避免 LLM 工具呼叫或 API 傳入的怪字串寫進資料庫。

追蹤清單
--------
- ``add_watchlist(session, stock_id, stock_name)``：
  - 已在清單（啟用中）→ ``WatchlistAlreadyExistsError``（使用者確認：回報「已在清單中」，聊天時 LLM 才能如實告知）
  - 曾被移除 → **恢復原紀錄**（is_active=True，更新名稱），不新增第二筆
  - 否則新增
- ``remove_watchlist(session, stock_id)``：軟刪除；不在清單（或已移除）→ ``WatchlistNotFoundError``
- ``get_active_watchlist(session)``：啟用中的清單，依 stock_id 排序
- ``get_watchlist_item(session, stock_id)``：啟用中的那一筆，沒有 → None

分析報告（使用者確認：每次分析都保留，查詢預設取最新）
------------------------------------------------------
- ``save_report(session, result: AnalysisResult) -> AnalysisReport``
- ``get_latest_report(session, stock_id, analysis_date=None)``：最新 generated_at 的一筆；
  指定 analysis_date 時只看那天
- ``get_report_history(session, stock_id, start=None, end=None, all_runs=False)``：
  analysis_date 由新到舊；預設每個分析日只取最新一份，``all_runs=True`` 列出每次重跑
- ``get_latest_reports(session)``：啟用中清單每檔的最新一份（沒有報告的股票不列出）
- ``to_stock_report(row)`` / ``to_stock_signals(row)``：把 JSON 欄位轉回 pydantic model

聊天紀錄
--------
- ``add_chat_message(session, session_id, role, content, related_stock_id=None)``
- ``get_chat_history(session, session_id, limit=50)``：依時間由舊到新，取最後 limit 則
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import AnalysisReport, ChatMessage, Watchlist
from backend.app.llm.report_schema import StockReport
from backend.app.signals.signal_builder import StockSignals

_STOCK_ID_PATTERN = re.compile(r"^\d{4,6}[A-Z]?$")


class CrudError(Exception):
    """資料存取例外基底。"""


class InvalidStockIdError(CrudError, ValueError):
    pass


class WatchlistAlreadyExistsError(CrudError):
    pass


class WatchlistNotFoundError(CrudError):
    pass


class ReportNotFoundError(CrudError):
    """查無分析報告（API 用）。"""


def normalize_stock_id(stock_id: str) -> str:
    normalized = (stock_id or "").strip().upper()
    if not _STOCK_ID_PATTERN.match(normalized):
        raise InvalidStockIdError(f"股票代號格式不正確：{stock_id!r}")
    return normalized


# ---------------------------------------------------------------------------
# 追蹤清單
# ---------------------------------------------------------------------------

def _find_watchlist(session: Session, stock_id: str) -> Watchlist | None:
    return session.scalars(select(Watchlist).where(Watchlist.stock_id == stock_id)).first()


def add_watchlist(session: Session, stock_id: str, stock_name: str | None = None) -> Watchlist:
    stock_id = normalize_stock_id(stock_id)
    row = _find_watchlist(session, stock_id)
    if row is not None and row.is_active:
        raise WatchlistAlreadyExistsError(f"{stock_id} 已在追蹤清單中")
    if row is None:
        row = Watchlist(stock_id=stock_id, stock_name=stock_name, is_active=True)
        session.add(row)
    else:
        row.is_active = True
        row.stock_name = stock_name or row.stock_name
    session.commit()
    return row


def remove_watchlist(session: Session, stock_id: str) -> Watchlist:
    stock_id = normalize_stock_id(stock_id)
    row = _find_watchlist(session, stock_id)
    if row is None or not row.is_active:
        raise WatchlistNotFoundError(f"{stock_id} 不在追蹤清單中")
    row.is_active = False
    session.commit()
    return row


def get_active_watchlist(session: Session) -> list[Watchlist]:
    return list(session.scalars(
        select(Watchlist).where(Watchlist.is_active.is_(True)).order_by(Watchlist.stock_id)
    ))


def get_watchlist_item(session: Session, stock_id: str) -> Watchlist | None:
    row = _find_watchlist(session, normalize_stock_id(stock_id))
    return row if row is not None and row.is_active else None


# ---------------------------------------------------------------------------
# 分析報告
# ---------------------------------------------------------------------------

def save_report(session: Session, result) -> AnalysisReport:
    report = result.report
    row = AnalysisReport(
        stock_id=normalize_stock_id(result.stock_id),
        analysis_date=result.analysis_date,
        generated_at=result.generated_at,
        llm_status=report.llm_status,
        signals_json=result.signals.model_dump(mode="json"),
        report_json=report.report.model_dump(mode="json") if report.report is not None else None,
        error=report.error,
        warnings=list(report.warnings),
        initial_warnings=list(report.initial_warnings),
        repair_attempts=report.repair_attempts,
        model=report.model,
        prompt_version=report.prompt_version,
        prompt_tokens=report.prompt_tokens,
        completion_tokens=report.completion_tokens,
    )
    session.add(row)
    session.commit()
    return row


_NEWEST_FIRST = (AnalysisReport.generated_at.desc(), AnalysisReport.id.desc())


def get_latest_report(session: Session, stock_id: str, analysis_date: date | None = None) -> AnalysisReport | None:
    query = select(AnalysisReport).where(AnalysisReport.stock_id == normalize_stock_id(stock_id))
    if analysis_date is not None:
        query = query.where(AnalysisReport.analysis_date == analysis_date)
    return session.scalars(query.order_by(*_NEWEST_FIRST).limit(1)).first()


def get_report_history(
    session: Session, stock_id: str, start: date | None = None, end: date | None = None, all_runs: bool = False,
) -> list[AnalysisReport]:
    query = select(AnalysisReport).where(AnalysisReport.stock_id == normalize_stock_id(stock_id))
    if start is not None:
        query = query.where(AnalysisReport.analysis_date >= start)
    if end is not None:
        query = query.where(AnalysisReport.analysis_date <= end)
    rows = list(session.scalars(query.order_by(AnalysisReport.analysis_date.desc(), *_NEWEST_FIRST)))
    if all_runs:
        return rows
    seen, latest_per_day = set(), []
    for row in rows:
        if row.analysis_date not in seen:
            seen.add(row.analysis_date)
            latest_per_day.append(row)
    return latest_per_day


def get_latest_reports(session: Session) -> list[AnalysisReport]:
    reports = (get_latest_report(session, item.stock_id) for item in get_active_watchlist(session))
    return [row for row in reports if row is not None]


def to_stock_report(row: AnalysisReport) -> StockReport | None:
    return None if row.report_json is None else StockReport.model_validate(row.report_json)


def to_stock_signals(row: AnalysisReport) -> StockSignals:
    return StockSignals.model_validate(row.signals_json)


# ---------------------------------------------------------------------------
# 聊天紀錄
# ---------------------------------------------------------------------------

def add_chat_message(
    session: Session, session_id: str, role: str, content: str, related_stock_id: str | None = None,
) -> ChatMessage:
    row = ChatMessage(session_id=session_id, role=role, content=content, related_stock_id=related_stock_id)
    session.add(row)
    session.commit()
    return row


def get_chat_history(session: Session, session_id: str, limit: int = 50) -> list[ChatMessage]:
    # Windows 的 datetime.now 解析度有限，同時寫入的訊息時間可能相同，以 id 作為次要排序
    newest = session.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit)
    )
    return list(reversed(list(newest)))
