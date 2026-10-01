"""分析報告查詢端點。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_session
from backend.app.api.schemas import ReportDetail, ReportSummary
from backend.app.db import crud
from backend.app.db.crud import ReportNotFoundError

router = APIRouter(prefix="/api/reports")


@router.get("/latest", response_model=list[ReportSummary])
def latest_reports(session: Session = Depends(get_session)):
    return [ReportSummary.from_row(row) for row in crud.get_latest_reports(session)]


@router.get("/{stock_id}/latest", response_model=ReportDetail)
def latest_report(stock_id: str, session: Session = Depends(get_session)):
    row = crud.get_latest_report(session, stock_id)
    if row is None:
        raise ReportNotFoundError(f"{crud.normalize_stock_id(stock_id)} 尚無分析報告")
    return ReportDetail.from_row(row)


@router.get("/{stock_id}/history", response_model=list[ReportSummary])
def report_history(
    stock_id: str, start: date | None = None, end: date | None = None, all_runs: bool = False,
    session: Session = Depends(get_session),
):
    rows = crud.get_report_history(session, stock_id, start=start, end=end, all_runs=all_runs)
    return [ReportSummary.from_row(row) for row in rows]
