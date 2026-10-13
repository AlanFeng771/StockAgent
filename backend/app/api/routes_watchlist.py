"""追蹤清單端點與健康檢查。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.deps import get_session
from backend.app.api.schemas import HealthOut, WatchlistIn, WatchlistItem
from backend.app.db import crud
from backend.app.pipeline.watchlist import add_stock_to_watchlist

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
    return add_stock_to_watchlist(session, body.stock_id, request.app.state.stock_lookup)


@router.delete("/watchlist/{stock_id}", response_model=WatchlistItem)
def remove_watchlist(stock_id: str, session: Session = Depends(get_session)):
    return crud.remove_watchlist(session, stock_id)
