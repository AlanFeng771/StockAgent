"""技術面訊號判斷。

規格（Stage 2 spec）
====================

``detect_technical_signals(df, params=TECHNICAL, signal_params=SIGNALS) -> TechnicalSignals | None``

輸入：``compute_technical`` 的輸出（單一股票）。不需事先排序。
資料筆數 < ``params.required_price_rows()`` → 回傳 None（資料不足，不產生訊號）。

輸出 ``TechnicalSignals``
-------------------------
- ``stock_id`` / ``as_of``：最新交易日
- ``snapshot``：最新交易日的數值（給 LLM 的事實）：close（原始價，對照現價用）、
  adj_close、change_pct（還原價單日漲跌%）、各均線、rsi*、k、d、macd_dif/signal/hist、
  bb_upper/middle/lower、volume（原始量）、volume_ratio（見下方量能）、atr
- ``signals``：已觸發的訊號清單（``Signal``），依 days_ago 遞增、同日依 name 排序

交叉事件（回看最近 ``cross_lookback_days`` 個交易日，含最新交易日）
-----------------------------------------------------------------
「A 穿越 B」：以 A − B 的正負號判斷，相等（0）不算任何一方；第 t 日為正、且 t 日之前
**最近一個非 0** 的值為負 → 黃金交叉（bullish）；反之 → 死亡交叉（bearish）。
因此「在下方 → 碰到 → 回到下方」不算交叉，「在上方 → 碰到 → 又往上」也不算。

- ``ma{短}_ma{中}_golden_cross`` / ``_death_cross``：ma_periods 前兩個（預設 MA5 / MA20）
- ``kd_golden_cross`` / ``kd_death_cross``：K 穿越 D；value = 當日 K；
  描述標示「低檔」（K < kd_oversold）/「高檔」（K > kd_overbought）
- ``macd_golden_cross`` / ``macd_death_cross``：DIF 穿越訊號線
- ``rsi{短}_rsi{長}_golden_cross`` / ``_death_cross``：rsi_periods 前兩個（預設 RSI6 / RSI12）

最新交易日的狀態（days_ago = 0）
-------------------------------
- ``ma_bullish_alignment`` / ``ma_bearish_alignment``：均線由短到長嚴格遞減 / 遞增
  （預設 MA5 > MA20 > MA60 為多頭排列）；其他情況不產生訊號
- ``above_ma{長}`` / ``below_ma{長}``：還原收盤價站上 / 跌破最長均線（預設 MA60 季線），
  value = 收盤、threshold = 均線；相等不產生
- ``rsi{n}_overbought`` / ``rsi{n}_oversold``：RSI > 過熱門檻 → bearish（回檔風險）；
  < 超賣門檻 → bullish（反彈機會）
- ``kd_overbought`` / ``kd_oversold``：K 值，方向解讀同 RSI
- ``macd_above_zero`` / ``macd_below_zero``：DIF > 0 → bullish；< 0 → bearish
- ``bollinger_above_upper`` / ``bollinger_below_lower``：還原收盤價突破上軌 / 跌破下軌，
  bias = neutral（可能是強勢也可能是過度延伸，交給 LLM 判斷）
- ``volume_surge`` / ``volume_shrink``：volume_ratio = 當日量 ÷ **前一日**的 20 日均量
  （不含當天）；> volume_surge_ratio 為爆量、< volume_shrink_ratio 為量縮；bias = neutral

門檻比較一律用嚴格大於/小於（剛好等於門檻不觸發）。
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
from pydantic import BaseModel

from backend.app.signals.config import SIGNALS, TECHNICAL, SignalParams, TechnicalParams
from backend.app.signals.models import Signal


class TechnicalSignals(BaseModel):
    stock_id: str
    as_of: date
    snapshot: dict[str, float]
    signals: list[Signal]


def detect_technical_signals(
    df: pd.DataFrame,
    params: TechnicalParams = TECHNICAL,
    signal_params: SignalParams = SIGNALS,
) -> TechnicalSignals | None:
    if len(df) < params.required_price_rows():
        return None
    df = df.sort_values("date").reset_index(drop=True)
    last = df.iloc[-1]
    as_of = last["date"].date()

    ma_short, ma_mid, ma_long = (f"ma{n}" for n in (*params.ma_periods[:2], params.ma_periods[-1]))
    rsi_short, rsi_long = (f"rsi{n}" for n in params.rsi_periods[:2])
    previous_vol_ma = df[f"vol_ma{max(params.volume_ma_periods)}"].iloc[-2]
    volume_ratio = last["adj_volume"] / previous_vol_ma if previous_vol_ma else np.nan

    snapshot_columns = [
        "close", "adj_close", *(f"ma{n}" for n in params.ma_periods), *(f"rsi{n}" for n in params.rsi_periods),
        "k", "d", "macd_dif", "macd_signal", "macd_hist", "bb_upper", "bb_middle", "bb_lower", "volume", "atr",
    ]
    snapshot = {column: float(last[column]) for column in snapshot_columns}
    snapshot["change_pct"] = float((last["adj_close"] / df["adj_close"].iloc[-2] - 1) * 100)
    snapshot["volume_ratio"] = float(volume_ratio)

    signals: list[Signal] = []
    lookback = signal_params.cross_lookback_days

    def add(name, category, bias, description, row_index=len(df) - 1, value=None, threshold=None):
        signals.append(Signal(
            name=name, category=category, bias=bias, description=description,
            date=df["date"].iloc[row_index].date(), days_ago=len(df) - 1 - row_index,
            value=None if value is None else float(value),
            threshold=None if threshold is None else float(threshold),
        ))

    def cross_events(a: str, b: str, prefix: str, category: str, label: str, describe_zone=False):
        for index, direction in _crosses(df[a] - df[b], lookback):
            golden = direction > 0
            zone = ""
            if describe_zone:
                k = df["k"].iloc[index]
                zone = "低檔" if k < signal_params.kd_oversold else "高檔" if k > signal_params.kd_overbought else ""
            add(
                f"{prefix}_{'golden' if golden else 'death'}_cross", category,
                "bullish" if golden else "bearish",
                f"{zone}{label}{'黃金交叉' if golden else '死亡交叉'}",
                row_index=index, value=df[a].iloc[index] if describe_zone else None,
            )

    cross_events(ma_short, ma_mid, f"{ma_short}_{ma_mid}", "trend", f"{ma_short.upper()} 與 {ma_mid.upper()} ")
    cross_events("k", "d", "kd", "momentum", "KD ", describe_zone=True)
    cross_events("macd_dif", "macd_signal", "macd", "trend", "MACD（DIF 與訊號線）")
    cross_events(rsi_short, rsi_long, f"{rsi_short}_{rsi_long}", "momentum", f"{rsi_short.upper()} 與 {rsi_long.upper()} ")

    ma_values = [last[f"ma{n}"] for n in params.ma_periods]
    labels = " > ".join(f"MA{n}" for n in params.ma_periods)
    if all(a > b for a, b in zip(ma_values, ma_values[1:])):
        add("ma_bullish_alignment", "trend", "bullish", f"均線多頭排列（{labels}）")
    elif all(a < b for a, b in zip(ma_values, ma_values[1:])):
        add("ma_bearish_alignment", "trend", "bearish", f"均線空頭排列（{labels.replace('>', '<')}）")

    if last["adj_close"] > last[ma_long]:
        add(f"above_{ma_long}", "trend", "bullish", f"收盤價站上 {ma_long.upper()}",
            value=last["adj_close"], threshold=last[ma_long])
    elif last["adj_close"] < last[ma_long]:
        add(f"below_{ma_long}", "trend", "bearish", f"收盤價跌破 {ma_long.upper()}",
            value=last["adj_close"], threshold=last[ma_long])

    for period, overbought, oversold in signal_params.rsi_thresholds:
        value = last[f"rsi{period}"]
        if value > overbought:
            add(f"rsi{period}_overbought", "momentum", "bearish", f"RSI{period} 過熱", value=value, threshold=overbought)
        elif value < oversold:
            add(f"rsi{period}_oversold", "momentum", "bullish", f"RSI{period} 超賣", value=value, threshold=oversold)

    if last["k"] > signal_params.kd_overbought:
        add("kd_overbought", "momentum", "bearish", "KD 過熱（K 值）", value=last["k"], threshold=signal_params.kd_overbought)
    elif last["k"] < signal_params.kd_oversold:
        add("kd_oversold", "momentum", "bullish", "KD 超賣（K 值）", value=last["k"], threshold=signal_params.kd_oversold)

    if last["macd_dif"] > 0:
        add("macd_above_zero", "trend", "bullish", "MACD DIF 在 0 軸之上", value=last["macd_dif"], threshold=0.0)
    elif last["macd_dif"] < 0:
        add("macd_below_zero", "trend", "bearish", "MACD DIF 在 0 軸之下", value=last["macd_dif"], threshold=0.0)

    if last["adj_close"] > last["bb_upper"]:
        add("bollinger_above_upper", "volatility", "neutral", "收盤價突破布林上軌",
            value=last["adj_close"], threshold=last["bb_upper"])
    elif last["adj_close"] < last["bb_lower"]:
        add("bollinger_below_lower", "volatility", "neutral", "收盤價跌破布林下軌",
            value=last["adj_close"], threshold=last["bb_lower"])

    if volume_ratio > signal_params.volume_surge_ratio:
        add("volume_surge", "volume", "neutral", "爆量（當日量 ÷ 前一日20日均量）",
            value=volume_ratio, threshold=signal_params.volume_surge_ratio)
    elif volume_ratio < signal_params.volume_shrink_ratio:
        add("volume_shrink", "volume", "neutral", "量縮（當日量 ÷ 前一日20日均量）",
            value=volume_ratio, threshold=signal_params.volume_shrink_ratio)

    signals.sort(key=lambda s: (s.days_ago, s.name))
    return TechnicalSignals(stock_id=str(last["stock_id"]), as_of=as_of, snapshot=snapshot, signals=signals)


def _crosses(diff: pd.Series, lookback: int) -> list[tuple[int, int]]:
    """回傳最近 lookback 筆內的交叉 [(列索引, +1 黃金 / -1 死亡)]；0 不算任何一方。"""
    sign = np.sign(diff).replace(0, np.nan)
    previous_nonzero = sign.ffill().shift()
    is_cross = sign.notna() & previous_nonzero.notna() & (sign != previous_nonzero)
    start = len(diff) - lookback
    return [(int(i), int(sign[i])) for i in diff.index[is_cross] if i >= start]
