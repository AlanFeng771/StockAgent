"""籌碼面訊號判斷（三大法人、融資融券）。

規格（Stage 2 spec）
====================

``detect_chip_signals(institutional, margin, prices, signal_params=SIGNALS) -> ChipSignals | None``

輸入
----
- ``institutional``：``get_institutional_investors`` 的輸出（單位：**股**）
- ``margin``：``get_margin_trading`` 的輸出（單位：**張**；由 2330 融資限額 6,483,092
  ≈ 總股數約 259 億股的 25% 換算確認）
- ``prices``：``adjust_prices`` 的輸出，用於成交量（原始 volume，股）與股價漲跌（adj_close）
三者皆不需事先排序。法人與融資皆為空 → 回傳 None。

籌碼資料的日期**獨立於股價**：實測 2026-10-01 下午股價已有當天資料，法人與融資只到
09-30。因此輸出分別標示 ``as_of_institutional`` / ``as_of_margin``，訊號的 days_ago
以各自資料的最新日為 0。

法人分類（FinMind investor_type → 本專案）
------------------------------------------
- 外資 foreign = Foreign_Investor + Foreign_Dealer_Self
- 投信 trust = Investment_Trust
- 自營商 dealer = Dealer_self + Dealer_Hedging（只列數值，不產生訊號）
某天缺少某類別視為 0。

snapshot（數值；算不出來時為 None）
-----------------------------------
- ``foreign_net_lots`` / ``trust_net_lots`` / ``dealer_net_lots``：最新一日買賣超（張 = 股 ÷ 1000）
- ``foreign_net_{N}d_lots`` / ``trust_net_{N}d_lots`` / ``dealer_net_{N}d_lots``：近 N 日合計（N = chip_sum_days）
- ``foreign_trust_net_{N}d_ratio_pct``：(外資 + 投信近 N 日合計股數) ÷ 同 N 個交易日的成交量股數 × 100；
  任一日沒有成交量資料 → None
- ``foreign_streak`` / ``trust_streak``：截至最新一日的連續天數，買超為正、賣超為負；
  當日買賣超為 0 → 0
- ``margin_balance_lots`` / ``short_balance_lots``：最新融資 / 融券餘額（張）
- ``margin_change_{N}d_pct``：最新融資餘額相對 N 個交易日前的變化%；筆數不足或 N 日前為 0 → None
- ``price_change_{N}d_pct``：融資最新日的還原收盤相對 N 個交易日前（以融資資料的日期對齊）的變化%
- ``short_margin_ratio_pct``：融券餘額 ÷ 融資餘額 × 100；融資餘額為 0 → None

訊號
----
- ``foreign_buy_streak`` / ``foreign_sell_streak`` / ``trust_buy_streak`` / ``trust_sell_streak``：
  連續天數 >= chip_streak_days；value = 連續天數、threshold = chip_streak_days；
  date = 連續區間的第一天，days_ago = 第一天距最新日幾個交易日（法人資料）
- ``margin_up_price_down``（bearish）：融資 N 日增幅 > margin_change_pct 且股價 N 日下跌
- ``margin_down_price_up``（bullish）：融資 N 日減幅 > margin_change_pct 且股價 N 日上漲
- ``high_short_margin_ratio``（neutral）：券資比 > short_margin_ratio_pct
門檻比較一律用嚴格大於/小於。訊號依 (days_ago, name) 排序。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
from pydantic import BaseModel

from backend.app.signals.config import SIGNALS, SignalParams
from backend.app.signals.models import Signal

INVESTOR_GROUPS = {
    "Foreign_Investor": "foreign",
    "Foreign_Dealer_Self": "foreign",
    "Investment_Trust": "trust",
    "Dealer_self": "dealer",
    "Dealer_Hedging": "dealer",
}


class ChipSignals(BaseModel):
    stock_id: str
    as_of_institutional: date | None
    as_of_margin: date | None
    snapshot: dict[str, float | None]
    signals: list[Signal]


def detect_chip_signals(
    institutional: pd.DataFrame,
    margin: pd.DataFrame,
    prices: pd.DataFrame,
    signal_params: SignalParams = SIGNALS,
) -> ChipSignals | None:
    if institutional.empty and margin.empty:
        return None
    n = signal_params.chip_sum_days
    stock_id = str((institutional if not institutional.empty else margin)["stock_id"].iloc[0])
    prices = prices.sort_values("date").set_index("date")
    snapshot: dict[str, float | None] = {}
    signals: list[Signal] = []

    as_of_institutional = None
    if institutional.empty:
        for key in ("foreign_net_lots", "trust_net_lots", "dealer_net_lots",
                    f"foreign_net_{n}d_lots", f"trust_net_{n}d_lots", f"dealer_net_{n}d_lots",
                    f"foreign_trust_net_{n}d_ratio_pct", "foreign_streak", "trust_streak"):
            snapshot[key] = None
    else:
        daily = _daily_net_by_group(institutional)
        as_of_institutional = daily.index[-1].date()
        recent = daily.tail(n)
        for group in ("foreign", "trust", "dealer"):
            snapshot[f"{group}_net_lots"] = float(daily[group].iloc[-1]) / 1000
            snapshot[f"{group}_net_{n}d_lots"] = float(recent[group].sum()) / 1000
        volume = prices["volume"].reindex(recent.index)
        snapshot[f"foreign_trust_net_{n}d_ratio_pct"] = (
            None if volume.isna().any() or volume.sum() == 0
            else float((recent["foreign"] + recent["trust"]).sum() / volume.sum() * 100)
        )
        for group, label in (("foreign", "外資"), ("trust", "投信")):
            streak = _streak(daily[group])
            snapshot[f"{group}_streak"] = float(streak)
            if abs(streak) >= signal_params.chip_streak_days:
                buying = streak > 0
                start = len(daily) - abs(streak)
                signals.append(Signal(
                    name=f"{group}_{'buy' if buying else 'sell'}_streak", category="chip",
                    bias="bullish" if buying else "bearish",
                    description=f"{label}連續{'買超' if buying else '賣超'} {abs(streak)} 天",
                    date=daily.index[start].date(), days_ago=abs(streak) - 1,
                    value=float(abs(streak)), threshold=float(signal_params.chip_streak_days),
                ))

    as_of_margin = None
    if margin.empty:
        for key in ("margin_balance_lots", "short_balance_lots", f"margin_change_{n}d_pct",
                    f"price_change_{n}d_pct", "short_margin_ratio_pct"):
            snapshot[key] = None
    else:
        margin = margin.sort_values("date").reset_index(drop=True)
        last = margin.iloc[-1]
        as_of_margin = last["date"].date()
        balance, short = float(last["margin_purchase_today_balance"]), float(last["short_sale_today_balance"])
        snapshot["margin_balance_lots"] = balance
        snapshot["short_balance_lots"] = short

        margin_change = price_change = None
        if len(margin) > n:
            base = margin.iloc[-1 - n]
            if base["margin_purchase_today_balance"]:
                margin_change = _pct_change(base["margin_purchase_today_balance"], balance)
            close_now, close_base = prices["adj_close"].get(last["date"]), prices["adj_close"].get(base["date"])
            if close_now is not None and close_base:
                price_change = _pct_change(close_base, close_now)
        snapshot[f"margin_change_{n}d_pct"] = None if margin_change is None else float(margin_change)
        snapshot[f"price_change_{n}d_pct"] = None if price_change is None else float(price_change)

        threshold = signal_params.margin_change_pct
        if margin_change is not None and price_change is not None:
            if margin_change > threshold and price_change < 0:
                signals.append(_margin_signal("margin_up_price_down", "bearish",
                                              f"融資 {n} 日增加但股價下跌（散戶接刀，籌碼凌亂）",
                                              as_of_margin, margin_change, threshold))
            elif margin_change < -threshold and price_change > 0:
                signals.append(_margin_signal("margin_down_price_up", "bullish",
                                              f"融資 {n} 日減少但股價上漲（籌碼沉澱）",
                                              as_of_margin, margin_change, -threshold))

        ratio = round(short * 100 / balance, 10) if balance else None
        snapshot["short_margin_ratio_pct"] = ratio
        if ratio is not None and ratio > signal_params.short_margin_ratio_pct:
            signals.append(_margin_signal("high_short_margin_ratio", "neutral", "券資比偏高（有軋空可能）",
                                          as_of_margin, ratio, signal_params.short_margin_ratio_pct))

    signals.sort(key=lambda s: (s.days_ago, s.name))
    return ChipSignals(
        stock_id=stock_id, as_of_institutional=as_of_institutional, as_of_margin=as_of_margin,
        snapshot=snapshot, signals=signals,
    )


def _daily_net_by_group(institutional: pd.DataFrame) -> pd.DataFrame:
    """每日各法人群組的買賣超股數（列 = 日期遞增，欄 = foreign/trust/dealer，缺的補 0）。"""
    grouped = institutional.assign(group=institutional["investor_type"].map(INVESTOR_GROUPS))
    daily = grouped.pivot_table(index="date", columns="group", values="net", aggfunc="sum", fill_value=0)
    return daily.reindex(columns=["foreign", "trust", "dealer"], fill_value=0).sort_index()


def _streak(net: pd.Series) -> int:
    """截至最後一天的連續買超（正）/賣超（負）天數；最後一天為 0 → 0。"""
    signs = list((net > 0).astype(int) - (net < 0).astype(int))
    last = signs[-1]
    if last == 0:
        return 0
    count = 0
    for sign in reversed(signs):
        if sign != last:
            break
        count += 1
    return count * last


def _pct_change(base: float, current: float) -> float:
    """先相減再相除並四捨五入到小數10位，避免浮點誤差讓「剛好等於門檻」被判成超過
    （例如 1050 / 1000 − 1 = 0.05000000000000004）。"""
    return round((current - base) / base * 100, 10)


def _margin_signal(name, bias, description, as_of, value, threshold) -> Signal:
    return Signal(
        name=name, category="chip", bias=bias, description=description,
        date=as_of, days_ago=0, value=float(value), threshold=float(threshold),
    )
