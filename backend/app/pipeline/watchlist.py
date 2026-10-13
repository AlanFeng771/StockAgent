"""加入追蹤清單（API 與聊天工具共用）。

``add_stock_to_watchlist(session, stock_id, stock_lookup) -> Watchlist``
- 代號正規化，格式錯 → ``InvalidStockIdError``
- 已在清單 → ``WatchlistAlreadyExistsError``（先檢查，避免不必要的 FinMind 呼叫）
- ``stock_lookup(stock_id)`` 查無 → ``StockNotFoundError``；名稱取自查到的 profile
"""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from backend.app.data_sources.stock_profile import StockProfile
from backend.app.db import crud
from backend.app.db.models import Watchlist
from backend.app.pipeline.analyze_stock import StockNotFoundError


def add_stock_to_watchlist(
    session: Session, stock_id: str, stock_lookup: Callable[[str], StockProfile | None],
) -> Watchlist:
    stock_id = crud.normalize_stock_id(stock_id)
    if crud.get_watchlist_item(session, stock_id) is not None:
        raise crud.WatchlistAlreadyExistsError(f"{stock_id} 已在追蹤清單中")
    profile = stock_lookup(stock_id)
    if profile is None:
        raise StockNotFoundError(f"查無股票代號 {stock_id}")
    return crud.add_watchlist(session, stock_id, profile.stock_name)
