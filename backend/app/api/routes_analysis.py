"""手動觸發分析端點（全清單背景執行、單檔同步執行，共用同一把鎖）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.deps import get_session, session_factory_of
from backend.app.api.schemas import ReportDetail
from backend.app.db import crud
from backend.app.pipeline.jobs import JobStatus

router = APIRouter(prefix="/api/analysis")


def _analyze_and_save(request: Request):
    analyzer = request.app.state.analyzer
    factory = session_factory_of(request)

    def run(stock_id: str):
        result = analyzer(stock_id)
        with factory() as session:
            return crud.save_report(session, result)

    return run


@router.post("/run", response_model=JobStatus, status_code=202)
def run_watchlist(request: Request, session: Session = Depends(get_session)):
    stock_ids = [item.stock_id for item in crud.get_active_watchlist(session)]
    return request.app.state.jobs.start_watchlist_job(stock_ids, _analyze_and_save(request))


@router.get("/status", response_model=JobStatus)
def analysis_status(request: Request):
    return request.app.state.jobs.status()


@router.post("/run/{stock_id}", response_model=ReportDetail)
def run_single(stock_id: str, request: Request):
    stock_id = crud.normalize_stock_id(stock_id)
    row = request.app.state.jobs.run_single(stock_id, _analyze_and_save(request))
    return ReportDetail.from_row(row)
