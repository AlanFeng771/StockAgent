from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from ta.momentum import RSIIndicator
from ta.trend import MACD
from ta.volatility import AverageTrueRange

from backend.app.indicators.technical import compute_technical
from backend.app.signals.config import TechnicalParams

INDICATOR_COLUMNS = [
    "ma5", "ma20", "ma60", "rsi6", "rsi12", "k", "d",
    "macd_dif", "macd_signal", "macd_hist",
    "bb_middle", "bb_upper", "bb_lower",
    "vol_ma5", "vol_ma20", "atr",
]


def make_adjusted(closes, highs=None, lows=None, volumes=None, start="2026-01-01"):
    """組出 adjust_prices 格式的輸入；adj_* 與原始值刻意不同，確保指標用的是 adj_*。"""
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    highs = closes + 1 if highs is None else np.asarray(highs, dtype=float)
    lows = closes - 1 if lows is None else np.asarray(lows, dtype=float)
    volumes = np.full(n, 1000.0) if volumes is None else np.asarray(volumes, dtype=float)
    return pd.DataFrame({
        "date": pd.bdate_range(start, periods=n),
        "stock_id": "2330",
        "open": closes * 10, "high": highs * 10, "low": lows * 10, "close": closes * 10,
        "volume": volumes * 10,
        "adj_factor": 1.0,
        "adj_open": closes, "adj_high": highs, "adj_low": lows, "adj_close": closes,
        "adj_volume": volumes,
    })


def random_walk(n=150, seed=0):
    rng = np.random.default_rng(seed)
    return 100 + np.cumsum(rng.normal(0, 1, n))


# ---------------------------------------------------------------------------
# 輸出格式
# ---------------------------------------------------------------------------

def test_output_has_original_and_indicator_columns_sorted_by_date():
    prices = make_adjusted(random_walk(80)).iloc[::-1]

    df = compute_technical(prices)

    assert list(df.columns) == list(prices.columns) + INDICATOR_COLUMNS
    assert df["date"].is_monotonic_increasing
    assert list(df.index) == list(range(80))


def test_empty_input_returns_empty_with_all_columns():
    prices = make_adjusted([]).iloc[0:0]

    df = compute_technical(prices)

    assert df.empty
    assert list(df.columns) == list(prices.columns) + INDICATOR_COLUMNS


def test_uses_adjusted_columns_not_raw():
    df = compute_technical(make_adjusted([10.0] * 30))

    # 原始價是 adj 的 10 倍；若誤用原始價，ma5 會是 100
    assert df["ma5"].iloc[-1] == pytest.approx(10.0)


def test_does_not_mutate_input():
    prices = make_adjusted(random_walk(40))
    snapshot = prices.copy()

    compute_technical(prices)

    pd.testing.assert_frame_equal(prices, snapshot)


# ---------------------------------------------------------------------------
# 均線、均量、布林
# ---------------------------------------------------------------------------

def test_moving_averages_and_insufficient_rows_are_nan():
    df = compute_technical(make_adjusted(list(range(1, 26)), volumes=list(range(1, 26))))

    assert df["ma5"].iloc[3] != df["ma5"].iloc[3]  # NaN：只有4筆
    assert df["ma5"].iloc[4] == pytest.approx(3.0)  # (1+2+3+4+5)/5
    assert df["ma20"].iloc[-1] == pytest.approx(np.mean(range(6, 26)))
    assert df["ma60"].isna().all()
    assert df["vol_ma5"].iloc[-1] == pytest.approx(np.mean(range(21, 26)))


def test_bollinger_uses_population_std():
    closes = random_walk(30)
    df = compute_technical(make_adjusted(closes))

    window = closes[-20:]
    middle, std = window.mean(), window.std(ddof=0)
    assert df["bb_middle"].iloc[-1] == pytest.approx(middle)
    assert df["bb_upper"].iloc[-1] == pytest.approx(middle + 2 * std)
    assert df["bb_lower"].iloc[-1] == pytest.approx(middle - 2 * std)


def test_custom_ma_periods_produce_matching_columns():
    params = TechnicalParams(ma_periods=(10,), volume_ma_periods=(3,))

    df = compute_technical(make_adjusted(random_walk(40)), params)

    assert "ma10" in df.columns and "ma5" not in df.columns
    assert "vol_ma3" in df.columns


# ---------------------------------------------------------------------------
# RSI、MACD：以 ta 套件作為獨立參考實作比對
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("period", [6, 12])
def test_rsi_matches_wilder_reference(period):
    closes = pd.Series(random_walk(120))
    df = compute_technical(make_adjusted(closes))

    expected = RSIIndicator(closes, window=period).rsi()
    pd.testing.assert_series_equal(df[f"rsi{period}"], expected, check_names=False, atol=1e-9)


def test_custom_rsi_periods_produce_matching_columns():
    df = compute_technical(make_adjusted(random_walk(40)), TechnicalParams(rsi_periods=(14,)))

    assert "rsi14" in df.columns and "rsi6" not in df.columns


def test_rsi_extremes():
    up = compute_technical(make_adjusted(list(range(1, 40))))
    down = compute_technical(make_adjusted(list(range(40, 1, -1))))

    assert up["rsi6"].iloc[-1] == pytest.approx(100.0)
    assert down["rsi6"].iloc[-1] == pytest.approx(0.0)


def test_macd_matches_reference():
    closes = pd.Series(random_walk(120))
    df = compute_technical(make_adjusted(closes))

    ref = MACD(closes, window_slow=26, window_fast=12, window_sign=9)
    last = df.iloc[-1]
    assert last["macd_dif"] == pytest.approx(ref.macd().iloc[-1])
    assert last["macd_signal"] == pytest.approx(ref.macd_signal().iloc[-1])
    assert last["macd_hist"] == pytest.approx(ref.macd_diff().iloc[-1])


# ---------------------------------------------------------------------------
# KD（台股算法，手算驗證）
# ---------------------------------------------------------------------------

def test_kd_taiwan_formula_hand_calculated():
    params = TechnicalParams(kd_period=3)
    # 收盤 10,11,12,11；高=收盤+1、低=收盤-1
    df = compute_technical(make_adjusted([10, 11, 12, 11]), params)

    # 第3筆：近3日最高13、最低9，RSV=(12-9)/(13-9)*100=75；K=2/3*50+1/3*75；D=2/3*50+1/3*K
    k3 = 2 / 3 * 50 + 1 / 3 * 75
    d3 = 2 / 3 * 50 + 1 / 3 * k3
    # 第4筆：近3日最高13、最低10，RSV=(11-10)/(13-10)*100
    rsv4 = 100 / 3
    k4 = 2 / 3 * k3 + 1 / 3 * rsv4
    d4 = 2 / 3 * d3 + 1 / 3 * k4

    assert df["k"].iloc[:2].isna().all()
    assert df["k"].iloc[2] == pytest.approx(k3)
    assert df["d"].iloc[2] == pytest.approx(d3)
    assert df["k"].iloc[3] == pytest.approx(k4)
    assert df["d"].iloc[3] == pytest.approx(d4)


def test_kd_flat_price_rsv_is_50():
    params = TechnicalParams(kd_period=3)
    flat = [10.0] * 5

    df = compute_technical(make_adjusted(flat, highs=flat, lows=flat), params)

    assert df["k"].iloc[-1] == pytest.approx(50.0)
    assert df["d"].iloc[-1] == pytest.approx(50.0)


def test_kd_stays_within_0_and_100():
    df = compute_technical(make_adjusted(random_walk(150, seed=3)))

    valid = df[["k", "d"]].dropna()
    assert ((valid >= 0) & (valid <= 100)).all().all()


def test_rsi_flat_price_is_neutral_50():
    df = compute_technical(make_adjusted([10.0] * 30))

    assert df["rsi12"].iloc[-1] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# ATR（Wilder，以 ta 套件為獨立參考）
# ---------------------------------------------------------------------------

def test_atr_matches_wilder_reference():
    rng = np.random.default_rng(5)
    closes = random_walk(120, seed=5)
    highs = closes + rng.uniform(0.1, 2.0, 120)
    lows = closes - rng.uniform(0.1, 2.0, 120)
    df = compute_technical(make_adjusted(closes, highs=highs, lows=lows))

    expected = AverageTrueRange(pd.Series(highs), pd.Series(lows), pd.Series(closes), window=14).average_true_range()
    assert df["atr"].iloc[:13].isna().all()  # ta 在這段填 0，本專案用 NaN 表示資料不足
    np.testing.assert_allclose(df["atr"].iloc[13:], expected.iloc[13:], rtol=1e-9)


def test_atr_uses_gap_from_previous_close():
    # 跳空：前收 10、今天 高12 低11 → TR = 12 − 10 = 2（不是 高−低 = 1）
    closes = [10.0] * 14 + [11.5]
    highs = [10.5] * 14 + [12.0]
    lows = [9.5] * 14 + [11.0]
    df = compute_technical(make_adjusted(closes, highs=highs, lows=lows), TechnicalParams(atr_period=14))

    # 前 14 筆 TR 皆為 1 → 第14筆 ATR = 1；第15筆 = (1×13 + 2) / 14
    assert df["atr"].iloc[13] == pytest.approx(1.0)
    assert df["atr"].iloc[14] == pytest.approx((13 + 2) / 14)
