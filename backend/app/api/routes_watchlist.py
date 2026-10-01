"""追蹤清單端點與健康檢查。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.deps import get_session
from backend.app.api.schemas import HealthOut, WatchlistIn, WatchlistItem
from backend.app.db import crud
from backend.app.db.crud import WatchlistAlreadyExistsError
from backend.app.pipeline.analyze_stock import StockNotFoundError

router = APIRouter(prefix="/api")


@router.get("/health", response_model=HealthOut)
def health(session: Session = Depends(get_session)) -> HealthOut:
    session.execute(text("SELECT 1"))
    return HealthOut(status="ok", database="ok")


@router.get("/watchlist", response_model=list[WatchlistItem])
def list_watchlist(session: Session = Depends(get_session)):
    return crud.get_active_watchlist(session)


@router.post("/watchlist", response_model=WatchlistItem, status_code=201)
def add_watchlist(body: WatchlistIn, request: Request, session: Session = Depends(get_session)):
    stock_id = crud.normalize_stock_id(body.stock_id)
    if crud.get_watchlist_item(session, stock_id) is not None:  # 先檢查，避免不必要的 FinMind 呼叫
        raise WatchlistAlreadyExistsError(f"{stock_id} 已在追蹤清單中")
    profile = request.app.state.stock_lookup(stock_id)
    if profile is None:
        raise StockNotFoundError(f"查無股票代號 {stock_id}")
    return crud.add_watchlist(session, stock_id, profile.stock_name)


@router.delete("/watchlist/{stock_id}", response_model=WatchlistItem)
def remove_watchlist(stock_id: str, session: Session = Depends(get_session)):
    return crud.remove_watchlist(session, stock_id)
