"""手動觸發分析端點（全清單背景執行、單檔同步執行，共用同一把鎖）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.api.deps import analyze_and_save_of, get_session
from backend.app.api.schemas import ReportDetail, RunRequest
from backend.app.db import crud
from backend.app.pipeline.jobs import JobStatus

router = APIRouter(prefix="/api/analysis")


@router.post("/run", response_model=JobStatus, status_code=202)
def run_watchlist(body: RunRequest, request: Request, session: Session = Depends(get_session)):
    stock_ids = [item.stock_id for item in crud.get_active_watchlist(session)]
    return request.app.state.jobs.start_watchlist_job(stock_ids, analyze_and_save_of(request))


@router.get("/status", response_model=JobStatus)
def analysis_status(request: Request):
    return request.app.state.jobs.status()


@router.post("/run/{stock_id}", response_model=ReportDetail)
def run_single(stock_id: str, body: RunRequest, request: Request):
    stock_id = crud.normalize_stock_id(stock_id)
    row = request.app.state.jobs.run_single(stock_id, analyze_and_save_of(request))
    return ReportDetail.from_row(row)
