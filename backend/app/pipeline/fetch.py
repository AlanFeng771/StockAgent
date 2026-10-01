"""依回溯期間抓齊單一股票分析所需的原始資料。

規格（Stage 3 先行，Stage 4 pipeline 共用）
==========================================

``fetch_stock_raw_data(client, stock_id, today, lookback=LOOKBACK) -> StockRawData``

- 各 dataset 的起始日 = today − ``lookback`` 對應天數，結束日 = today
- 除權息、面額變更與股價同一區間（還原只需要股價區間內的事件）
- 新聞抓 ``lookback.news`` 天（含今天），即起始日 = today − (news − 1)
- 股票基本資料為全市場查詢（不帶日期）
- client 的例外（FinMind 額度、token 等）原樣往上拋，由上層決定如何處理
"""

from __future__ import annotations

from datetime import date, timedelta

from backend.app.signals.config import LOOKBACK, LookbackDays
from backend.app.signals.signal_builder import StockRawData


def fetch_stock_raw_data(client, stock_id: str, today: date, lookback: LookbackDays = LOOKBACK) -> StockRawData:
    end = today.isoformat()

    def start(days: int) -> str:
        return (today - timedelta(days=days)).isoformat()

    price_start = start(lookback.price)
    return StockRawData(
        stock_info=client.get_stock_info(),
        prices=client.get_price(stock_id, price_start, end),
        dividends=client.get_dividend_result(stock_id, price_start, end),
        splits=client.get_split_price(price_start, end),
        institutional=client.get_institutional_investors(stock_id, start(lookback.institutional), end),
        margin=client.get_margin_trading(stock_id, start(lookback.margin), end),
        revenue=client.get_month_revenue(stock_id, start(lookback.month_revenue), end),
        financials=client.get_financial_statement(stock_id, start(lookback.financial_statement), end),
        valuation=client.get_valuation_ratios(stock_id, start(lookback.valuation), end),
        news=client.get_news(stock_id, start(lookback.news - 1), end),
    )
