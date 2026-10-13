"""最新報價（聊天工具 get_latest_price 使用）。

規格（Stage 8 spec；已拍板決策 1A：免費方案無即時報價）
====================================================

``QuoteProvider``（Protocol）：``get_latest_quote(stock_id) -> PriceQuote | None``
之後升級 FinMind sponsor（即時報價）只需換實作。

``FinMindQuoteProvider(client=None, settings=None, today=date.today, lookback_days=14)``
- 取 ``today - lookback_days`` ~ ``today`` 的日K（**原始價**，不還原：報價要和看盤軟體一致），回傳最後一筆
  （14 天涵蓋春節等長假）；沒有資料 → None
- ``change`` / ``change_pct``：與前一筆收盤相比（四捨五入到小數 2 位）；只有一筆 → None。
  除權息當天會包含除權息造成的價差（未用參考價）
- ``volume_lots``：成交張數 = 成交股數 // 1000
- ``note``：固定標明「非即時價，為 YYYY-MM-DD 收盤」，讓 LLM 回覆不會講成現在價格
- client 為 None 時第一次查詢才依設定建立（建立 app 時不連 FinMind）
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Protocol

from pydantic import BaseModel

from backend.app.config import Settings


class PriceQuote(BaseModel):
    stock_id: str
    date: date
    open: float
    high: float
    low: float
    close: float
    prev_close: float | None
    change: float | None
    change_pct: float | None
    volume_lots: int
    note: str


class QuoteProvider(Protocol):
    def get_latest_quote(self, stock_id: str) -> PriceQuote | None: ...


class FinMindQuoteProvider:
    def __init__(
        self,
        client: Any = None,
        settings: Settings | None = None,
        today: Callable[[], date] = date.today,
        lookback_days: int = 14,
    ) -> None:
        self._client = client
        self._settings = settings
        self._today = today
        self._lookback_days = lookback_days

    def get_latest_quote(self, stock_id: str) -> PriceQuote | None:
        if self._client is None:
            from backend.app.data_sources.finmind_client import create_finmind_client
            self._client = create_finmind_client(self._settings)
        today = self._today()
        start = today - timedelta(days=self._lookback_days)
        prices = self._client.get_price(stock_id, start.isoformat(), today.isoformat())
        if prices.empty:
            return None
        prices = prices.sort_values("date")
        last = prices.iloc[-1]
        prev_close = float(prices.iloc[-2]["close"]) if len(prices) > 1 else None
        close = float(last["close"])
        change = round(close - prev_close, 2) if prev_close is not None else None
        change_pct = round((close - prev_close) / prev_close * 100, 2) if prev_close else None
        day = last["date"].date()
        return PriceQuote(
            stock_id=stock_id, date=day, open=float(last["open"]), high=float(last["high"]),
            low=float(last["low"]), close=close, prev_close=prev_close, change=change, change_pct=change_pct,
            volume_lots=int(last["volume"]) // 1000, note=f"非即時價，為 {day.isoformat()} 收盤",
        )
