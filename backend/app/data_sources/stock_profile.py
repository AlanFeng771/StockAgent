"""單一股票的基本資料（名稱、產業、市場、商品類別）。

規格（Stage 2 補充 spec）
========================

``resolve_stock_profile(info, stock_id) -> StockProfile | None``

``info`` 為 ``FinMindClient.get_stock_info()`` 的輸出（全市場）。找不到代號 → None。

- 只採用該代號**最新日期**的列；全部列都沒有日期（NaT）時才用無日期的列
- ``stock_name``：去除前後空白與結尾星號（實測 6763 最新一列為 "綠界科技*"）
- ``industries``：最新日期各列的產業別，去重後排序（實測 2330 同時有「半導體業」「電子工業」）
- ``market``：twse / tpex / emerging
- ``kind``：決定價格升降單位適用哪一套規則
  - ``fund``：ETF、上櫃ETF、上櫃指數股票型基金(ETF)、受益證券（REITs）——
    證交所受益憑證買賣辦法第7條第2項（114.09.30）：未滿50元 0.01、50元以上 0.05
  - ``other``：存託憑證、ETN —— 升降單位規則尚未查證，不做價位對齊
  - ``stock``：其餘 —— 證交所營業細則第62條（115.09.24 版本查證）六級距；
    上櫃股票暫採同一規則（只查到興櫃辦法同表，上櫃條文待查證）
"""

from __future__ import annotations

from typing import Literal

import pandas as pd
from pydantic import BaseModel

FUND_CATEGORIES = {"ETF", "上櫃ETF", "上櫃指數股票型基金(ETF)", "受益證券"}
OTHER_CATEGORIES = {"存託憑證", "ETN", "指數投資證券(ETN)"}


class StockProfile(BaseModel):
    stock_id: str
    stock_name: str
    industries: list[str]
    market: str
    kind: Literal["stock", "fund", "other"]


def resolve_stock_profile(info: pd.DataFrame, stock_id: str) -> StockProfile | None:
    rows = info[info["stock_id"] == stock_id]
    if rows.empty:
        return None
    dated = rows[rows["date"].notna()]
    latest = dated[dated["date"] == dated["date"].max()] if not dated.empty else rows

    industries = sorted(set(latest["industry_category"].dropna()))
    if FUND_CATEGORIES & set(industries):
        kind = "fund"
    elif OTHER_CATEGORIES & set(industries):
        kind = "other"
    else:
        kind = "stock"
    return StockProfile(
        stock_id=stock_id,
        stock_name=str(latest["stock_name"].iloc[-1]).strip().rstrip("*").strip(),
        industries=industries,
        market=str(latest["market"].iloc[-1]),
        kind=kind,
    )
