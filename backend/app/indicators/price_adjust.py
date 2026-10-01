"""自行計算還原股價（向前還原）。

FinMind 的還原股價 ``taiwan_stock_daily_adj`` 為 sponsor 付費限定，免費方案改用
除權息結果（``get_dividend_result``）＋面額變更（``get_split_price``）自行計算。

規格（Stage 2 spec）
====================

``adjust_prices(prices, dividends, splits) -> DataFrame``

輸入
----
- ``prices``：``FinMindClient.get_price`` 的輸出（單一股票），欄位至少含
  date, stock_id, open, high, low, close, volume；不需事先排序
- ``dividends``：``FinMindClient.get_dividend_result`` 的輸出，欄位至少含
  date, stock_id, before_price, reference_price
- ``splits``：``FinMindClient.get_split_price`` 的輸出（**全市場**），欄位至少含
  date, stock_id, before_price, after_price；函式內自行篩出該股票

事件與調整係數
--------------
- 除權息：係數 = ``reference_price / before_price``（只調價格，股數不變）
- 面額變更/分割：係數 = ``after_price / before_price``（價格與成交量都要調）
- ``before_price`` 已用真實API驗證等於事件前一個交易日收盤價（0056、2330、6763、8932）
- 某一列的累積係數 = 該列日期**之後**（不含當天）所有事件係數的連乘；
  事件當天及之後的列不受該事件影響
- 只採用日期落在「第一筆股價之後、最後一筆股價當天或之前」的事件；
  晚於最後一筆股價的事件忽略（否則最新價會被改動）
- 無效事件（before_price <= 0、或參考價缺值/<= 0）忽略，不丟例外
- 同一天多個事件：係數相乘

輸出
----
原 ``prices`` 全部欄位（依 date 遞增排序、index 重設）再加上：
- ``adj_factor``：價格累積係數（無事件時為 1.0）
- ``adj_open`` / ``adj_high`` / ``adj_low`` / ``adj_close``：原始價 × ``adj_factor``
- ``adj_volume``：原始量 ÷ 分割累積係數（只受分割影響）

不變條件：**最新一筆的 adj_* 必等於原始值**（還原後的價格與現價同一尺度，
技術指標算出的支撐壓力位可直接對照現價）。

用法原則：技術指標一律用 adj_*；買賣點、現價等「價位」用原始價。

已知限制
--------
- 配股（除權）也會增加股數，但結果表沒有拆出股票股利比例，``adj_volume`` 不調整
  配股，只調整分割；配股比例通常為個位數%，對量能指標影響有限
- 減資尚未納入（見 PLAN.md：欄位未驗證）

``prices`` 為空時回傳含上述所有欄位的空 DataFrame。
"""

from __future__ import annotations

import pandas as pd

_ADJ_COLUMNS = ["adj_factor", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume"]


def adjust_prices(prices: pd.DataFrame, dividends: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    out = prices.sort_values("date").reset_index(drop=True)
    if out.empty:
        return out.reindex(columns=[*out.columns, *_ADJ_COLUMNS])

    stock_id = out["stock_id"].iloc[0]
    first_date, last_date = out["date"].iloc[0], out["date"].iloc[-1]
    dividend_events = _events(dividends, stock_id, "reference_price", first_date, last_date)
    split_events = _events(splits, stock_id, "after_price", first_date, last_date)

    price_factor = pd.Series(1.0, index=out.index)
    split_factor = pd.Series(1.0, index=out.index)
    for event_date, factor in dividend_events:
        price_factor[out["date"] < event_date] *= factor
    for event_date, factor in split_events:
        before_event = out["date"] < event_date
        price_factor[before_event] *= factor
        split_factor[before_event] *= factor

    out["adj_factor"] = price_factor
    for column in ("open", "high", "low", "close"):
        out[f"adj_{column}"] = out[column] * price_factor
    out["adj_volume"] = out["volume"] / split_factor
    return out


def _events(
    events: pd.DataFrame, stock_id: str, after_column: str,
    first_date: pd.Timestamp, last_date: pd.Timestamp,
) -> list[tuple[pd.Timestamp, float]]:
    """篩出該股票、落在股價區間內、數值有效的事件，回傳 [(事件日, 調整係數)]。"""
    before = events["before_price"]
    after = events[after_column]
    dates = pd.to_datetime(events["date"])
    valid = (
        (events["stock_id"] == stock_id)
        & (before > 0) & (after > 0)
        & (dates > first_date) & (dates <= last_date)
    )
    return list(zip(dates[valid], (after[valid] / before[valid]).astype(float)))
