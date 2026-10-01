"""技術指標數值計算。

規格（Stage 2 spec）
====================

``compute_technical(prices, params=TECHNICAL) -> DataFrame``

輸入：``adjust_prices`` 的輸出（單一股票），使用 adj_high / adj_low / adj_close /
adj_volume 計算；**一律用還原價**，避免除權息、面額變更造成假訊號。不需事先排序。

輸出：原欄位（依 date 遞增、index 重設）再加上下列欄位。資料筆數不足某指標的
週期時，該列為 NaN（不補值、不丟例外）；「資料是否足夠產生訊號」由訊號層依
``TechnicalParams.required_price_rows()`` 判斷。

- ``ma{n}``：收盤價 n 日簡單移動平均，n 取自 ``params.ma_periods``（預設 ma5/ma20/ma60）
- ``rsi{n}``：RSI，n 取自 ``params.rsi_periods``（預設 rsi6/rsi12），Wilder 平滑（α = 1/n）；只漲不跌時為 100、只跌不漲時為 0、
  完全沒漲跌時為 50（``ta`` 套件此情況回 100，本專案改為中性值）
- ``k`` / ``d``：台股 KD
    RSV = (收盤 − 近 N 日最低) / (近 N 日最高 − 近 N 日最低) × 100
    K = (1 − 1/s) × 前一日K + (1/s) × RSV；D = (1 − 1/s) × 前一日D + (1/s) × K
    （s = ``kd_smooth``，預設 3 → 2/3 與 1/3）
    第一個算得出 RSV 的那天，前一日 K、D 視為 50
    近 N 日最高 = 最低（價格完全沒動）時 RSV 取 50（本專案的決定，避免除以 0）
    註：``ta`` 套件的 StochasticOscillator 是 K = RSV、D = 3 日簡單平均，與台股慣用
    算法不同，所以自行實作
- ``macd_dif`` = EMA(fast) − EMA(slow)；``macd_signal`` = EMA(signal) of DIF；
  ``macd_hist`` = DIF − signal（台股看盤軟體的 DIF / MACD / OSC）。
  EMA 用 ``adjust=False``，第一筆以該筆收盤價起算
- ``bb_middle`` = 收盤 period 日均線；``bb_upper`` / ``bb_lower`` = middle ± k × 標準差
  （母體標準差 ddof=0，依 Bollinger 原始定義）
- ``vol_ma{n}``：成交量（adj_volume）n 日均量，n 取自 ``params.volume_ma_periods``
- ``atr``：平均真實波幅，Wilder 算法（與 ``ta`` 套件一致）：
    TR = max(高−低, |高−前收|, |低−前收|)，第一筆沒有前收時 TR = 高−低
    第 period 筆 ATR = 前 period 筆 TR 的簡單平均；之後 ATR = (前ATR × (period−1) + TR) / period
    之前的列為 NaN（``ta`` 填 0，本專案以 NaN 表示資料不足）
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.app.signals.config import TECHNICAL, TechnicalParams


def compute_technical(prices: pd.DataFrame, params: TechnicalParams = TECHNICAL) -> pd.DataFrame:
    out = prices.sort_values("date").reset_index(drop=True)
    close, high, low, volume = out["adj_close"], out["adj_high"], out["adj_low"], out["adj_volume"]

    for n in params.ma_periods:
        out[f"ma{n}"] = close.rolling(n).mean()
    for n in params.rsi_periods:
        out[f"rsi{n}"] = _rsi(close, n)
    out["k"], out["d"] = _kd(close, high, low, params.kd_period, params.kd_smooth)

    dif = _ema(close, params.macd_fast) - _ema(close, params.macd_slow)
    out["macd_dif"] = dif
    out["macd_signal"] = _ema(dif, params.macd_signal)
    out["macd_hist"] = dif - out["macd_signal"]

    middle = close.rolling(params.bollinger_period).mean()
    std = close.rolling(params.bollinger_period).std(ddof=0)
    out["bb_middle"] = middle
    out["bb_upper"] = middle + params.bollinger_std * std
    out["bb_lower"] = middle - params.bollinger_std * std

    for n in params.volume_ma_periods:
        out[f"vol_ma{n}"] = volume.rolling(n).mean()
    out["atr"] = _atr(high, low, close, params.atr_period)
    return out


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1,
    ).max(axis=1)
    values = [np.nan] * len(true_range)
    if len(true_range) >= period:
        values[period - 1] = true_range.iloc[:period].mean()
        for i in range(period, len(true_range)):
            values[i] = (values[i - 1] * (period - 1) + true_range.iloc[i]) / period
    return pd.Series(values, index=close.index, dtype=float)


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, min_periods=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int) -> pd.Series:
    change = close.diff()
    gain = change.where(change > 0, 0.0)
    loss = -change.where(change < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = 100 - 100 / (1 + avg_gain / avg_loss)
    rsi = rsi.where(avg_loss != 0, 100.0)
    rsi = rsi.where((avg_gain != 0) | (avg_loss != 0), 50.0)
    return rsi.where(avg_gain.notna())


def _kd(close: pd.Series, high: pd.Series, low: pd.Series, period: int, smooth: int) -> tuple[pd.Series, pd.Series]:
    highest = high.rolling(period).max()
    lowest = low.rolling(period).min()
    span = highest - lowest
    with np.errstate(divide="ignore", invalid="ignore"):
        rsv = ((close - lowest) / span * 100).where(span != 0, 50.0).where(span.notna())

    weight = 1 / smooth
    k_values, d_values = [], []
    prev_k = prev_d = 50.0
    for value in rsv:
        if np.isnan(value):
            k_values.append(np.nan)
            d_values.append(np.nan)
            continue
        prev_k = (1 - weight) * prev_k + weight * value
        prev_d = (1 - weight) * prev_d + weight * prev_k
        k_values.append(prev_k)
        d_values.append(prev_d)
    return pd.Series(k_values, index=close.index), pd.Series(d_values, index=close.index)
