"""支撐 / 壓力價位與填息價（給 LLM 定買賣點用，不讓它自己編數字）。

規格（Stage 2 補充 spec，2026-10-01 使用者確認）
==============================================

``build_price_levels(df, dividends, splits, kind, signal_params=SIGNALS) -> PriceLevels``

輸入：``compute_technical`` 的輸出（單一股票，含原始 high/low/close 與 adj_* 與均線/布林）；
``dividends`` / ``splits`` 為 client 原始輸出；``kind`` 為 ``StockProfile.kind``（決定升降單位）。

為什麼用還原價：價位要和現價比較，必須同一尺度。還原價最新一筆等於現價；事件前的原始價
不是今天的等值價格（例：0056 06-23 原始高 54.90 還原後只有 53.42，08-14 的 54.00 才是
近 60 日真正最高；6763 面額變更前的 498 若當壓力會是現價 11 倍）。

價位來源
--------
- 近 N 日最高 / 最低（N 取自 ``price_level_windows``，預設 20、60 個交易日），用 adj_high / adj_low；
  同值時取較近的那天。20 日與 60 日剛好是同一天同一價時合併為一筆，source 以「、」串接
- 最新一日的 MA（各 ``ma_periods``）、布林上軌 / 下軌（本來就是還原價尺度，沒有原始價對照）

每個價位 ``PriceLevel``
-----------------------
- ``price``：還原價對齊升降單位後的合法掛單價（``ticks.round_to_tick``）
- ``adjusted_price``：對齊前的還原價
- ``chart_price``：看盤軟體（原始價）上顯示的價格，只在該價位的日期之後到最新日之間發生
  **除權息**時提供，形成「解套賣壓 / 支撐區間」：還原價（把股息算進去的投資人）～原始價
  （只記得原本買價的投資人）。之後若有**面額變更**，原始價已無比較意義 → None
- ``date``：最高/最低發生日；均線、布林為 None
- ``distance_pct``：(adjusted_price − 現價) ÷ 現價 × 100

分類：adjusted_price < 現價 → supports（由近到遠，即價格由高到低）；> 現價 → resistances
（由近到遠，即價格由低到高）；等於現價不列入。

``flags``：``new_high_{N}d`` / ``new_low_{N}d`` —— 最新一日的 adj_high / adj_low 等於近 N 日最高 / 最低
（上方 / 下方沒有近期價位時，LLM 應據此描述「創 N 日新高，上方無近期壓力」，不得自編價位）。

``fill_gap``（填息價，原始價定義）：股價區間內**最近一次**除權息；``fill_price`` = 除權息前一日
收盤（before_price）；``filled_date`` = 除權息日（含）之後第一個原始收盤價 >= fill_price 的日子
（本專案以收盤價判定）。區間內沒有除權息、或之後發生面額變更 → None。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel

from backend.app.signals.calc import pct_change
from backend.app.signals.config import SIGNALS, TECHNICAL, SignalParams, TechnicalParams
from backend.app.signals.ticks import round_to_tick


class PriceLevel(BaseModel):
    source: str
    price: float
    adjusted_price: float
    chart_price: float | None
    date: date | None
    distance_pct: float


class FillGap(BaseModel):
    ex_date: date
    dividend: float
    fill_price: float
    filled: bool
    filled_date: date | None


class PriceLevels(BaseModel):
    as_of: date
    close: float
    kind: str
    supports: list[PriceLevel]
    resistances: list[PriceLevel]
    flags: dict[str, bool]
    fill_gap: FillGap | None


def build_price_levels(
    df: pd.DataFrame,
    dividends: pd.DataFrame,
    splits: pd.DataFrame,
    kind: str,
    signal_params: SignalParams = SIGNALS,
    params: TechnicalParams = TECHNICAL,
) -> PriceLevels:
    df = df.sort_values("date").reset_index(drop=True)
    last = df.iloc[-1]
    stock_id = last["stock_id"]
    first_date, last_date = df["date"].iloc[0], last["date"]
    close = float(last["close"])
    dividend_dates = _event_dates(dividends, stock_id, first_date, last_date)
    split_dates = _event_dates(splits, stock_id, first_date, last_date)

    def chart_price_for(when: pd.Timestamp, raw: float) -> float | None:
        if any(d > when for d in split_dates) or not any(d > when for d in dividend_dates):
            return None
        return float(raw)

    # (source, adjusted, chart_price, date)
    candidates: list[tuple[str, float, float | None, date | None]] = []
    flags: dict[str, bool] = {}
    for n in signal_params.price_level_windows:
        window = df.tail(n)
        for label, adj_col, raw_col, pick in (("最高", "adj_high", "high", "max"), ("最低", "adj_low", "low", "min")):
            values = window[adj_col]
            extreme = values.max() if pick == "max" else values.min()
            index = values[values == extreme].index[-1]  # 同值取較近的那天
            when = df.at[index, "date"]
            candidates.append((f"{n}日{label}", float(extreme), chart_price_for(when, df.at[index, raw_col]), when.date()))
            flags[f"new_{'high' if pick == 'max' else 'low'}_{n}d"] = bool(last[adj_col] == extreme)

    for n in params.ma_periods:
        candidates.append((f"MA{n}", float(last[f"ma{n}"]), None, None))
    candidates.append(("布林上軌", float(last["bb_upper"]), None, None))
    candidates.append(("布林下軌", float(last["bb_lower"]), None, None))

    merged: dict[tuple, list] = {}
    for source, adjusted, chart, when in candidates:
        key = (adjusted, chart, when)
        merged.setdefault(key, []).append(source)

    supports, resistances = [], []
    for (adjusted, chart, when), sources in merged.items():
        if pd.isna(adjusted) or adjusted == close:
            continue
        level = PriceLevel(
            source="、".join(sources), price=round_to_tick(adjusted, kind), adjusted_price=adjusted,
            chart_price=chart, date=when, distance_pct=pct_change(close, adjusted),
        )
        (supports if adjusted < close else resistances).append(level)
    supports.sort(key=lambda lv: -lv.adjusted_price)
    resistances.sort(key=lambda lv: lv.adjusted_price)

    return PriceLevels(
        as_of=last_date.date(), close=close, kind=kind, supports=supports, resistances=resistances,
        flags=flags, fill_gap=_fill_gap(df, dividends, stock_id, first_date, last_date, split_dates),
    )


def _event_dates(events: pd.DataFrame, stock_id: str, first: pd.Timestamp, last: pd.Timestamp) -> list[pd.Timestamp]:
    dates = pd.to_datetime(events.loc[events["stock_id"] == stock_id, "date"])
    return sorted(d for d in dates if first < d <= last)


def _fill_gap(df, dividends, stock_id, first_date, last_date, split_dates) -> FillGap | None:
    events = dividends[dividends["stock_id"] == stock_id].assign(date=lambda d: pd.to_datetime(d["date"]))
    events = events[(events["date"] > first_date) & (events["date"] <= last_date)].sort_values("date")
    if events.empty:
        return None
    event = events.iloc[-1]
    if any(d > event["date"] for d in split_dates):
        return None
    fill_price = float(event["before_price"])
    after = df[(df["date"] >= event["date"]) & (df["close"] >= fill_price)]
    filled_date = None if after.empty else after["date"].iloc[0].date()
    return FillGap(
        ex_date=event["date"].date(), dividend=float(event["dividend"]), fill_price=fill_price,
        filled=filled_date is not None, filled_date=filled_date,
    )
