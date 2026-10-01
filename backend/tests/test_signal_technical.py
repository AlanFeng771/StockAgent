from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.signals.config import TECHNICAL, SignalParams
from backend.app.signals.technical_signals import detect_technical_signals

ROWS = TECHNICAL.required_price_rows()  # 88


def make_frame(rows: int = ROWS, **overrides) -> pd.DataFrame:
    """建一個「什麼訊號都不觸發」的中性指標表，再用 overrides 覆寫最後幾筆。

    overrides 的值是 list，對齊到最後 len(list) 筆；例如 k=[10, 30] 代表倒數第2筆K=10、最新K=30。
    """
    df = pd.DataFrame({
        "date": pd.bdate_range("2026-01-01", periods=rows),
        "stock_id": "2330",
        "close": 1000.0, "adj_close": 100.0, "volume": 10_000.0, "adj_volume": 1000.0,
        "ma5": 100.0, "ma20": 100.0, "ma60": 100.0,
        "rsi6": 50.0, "rsi12": 50.0, "k": 50.0, "d": 50.0,
        "macd_dif": 0.0, "macd_signal": 0.0, "macd_hist": 0.0,
        "bb_middle": 100.0, "bb_upper": 110.0, "bb_lower": 90.0,
        "vol_ma5": 1000.0, "vol_ma20": 1000.0,
    })
    for column, values in overrides.items():
        df.loc[df.index[-len(values):], column] = values
    return df


def names(result) -> list[str]:
    return [s.name for s in result.signals]


def find(result, name):
    matches = [s for s in result.signals if s.name == name]
    assert len(matches) == 1, f"{name} 出現 {len(matches)} 次：{names(result)}"
    return matches[0]


# ---------------------------------------------------------------------------
# 資料量、輸出格式
# ---------------------------------------------------------------------------

def test_insufficient_rows_returns_none():
    assert detect_technical_signals(make_frame(rows=ROWS - 1)) is None


def test_neutral_frame_has_no_signals_and_full_snapshot():
    result = detect_technical_signals(make_frame())

    assert result.signals == []
    assert result.stock_id == "2330"
    assert result.as_of == pd.bdate_range("2026-01-01", periods=ROWS)[-1].date()
    for key in [
        "close", "adj_close", "change_pct", "ma5", "ma20", "ma60", "rsi6", "rsi12", "k", "d",
        "macd_dif", "macd_signal", "macd_hist", "bb_upper", "bb_middle", "bb_lower",
        "volume", "volume_ratio",
    ]:
        assert key in result.snapshot
    assert result.snapshot["close"] == 1000.0  # 原始價
    assert result.snapshot["adj_close"] == 100.0


def test_change_pct_uses_adjusted_close():
    result = detect_technical_signals(make_frame(adj_close=[100.0, 102.0]))

    assert result.snapshot["change_pct"] == pytest.approx(2.0)


def test_unsorted_input_is_handled():
    df = make_frame(k=[10.0, 30.0], d=[20.0, 20.0]).iloc[::-1]

    assert "kd_golden_cross" in names(detect_technical_signals(df))


# ---------------------------------------------------------------------------
# 交叉事件
# ---------------------------------------------------------------------------

def test_kd_golden_cross_today_low_zone():
    result = detect_technical_signals(make_frame(k=[10.0, 18.0], d=[15.0, 16.0]))

    signal = find(result, "kd_golden_cross")
    assert signal.bias == "bullish"
    assert signal.days_ago == 0
    assert signal.value == pytest.approx(18.0)
    assert "低檔" in signal.description


def test_kd_death_cross_high_zone():
    result = detect_technical_signals(make_frame(k=[90.0, 84.0], d=[85.0, 86.0]))

    signal = find(result, "kd_death_cross")
    assert signal.bias == "bearish"
    assert "高檔" in signal.description


def test_cross_within_lookback_reports_date_and_days_ago():
    # K 從 40 升到 60 的那天穿越 D（倒數第5筆，days_ago=4），之後維持在D之上
    df = make_frame(k=[40.0, 60.0, 61.0, 62.0, 63.0, 64.0], d=[50.0] * 6)
    result = detect_technical_signals(df)

    signal = find(result, "kd_golden_cross")
    assert signal.days_ago == 4
    assert signal.date == df["date"].iloc[-5].date()


def test_cross_older_than_lookback_is_ignored():
    df = make_frame(k=[40.0, 60.0, 61.0, 62.0, 63.0, 64.0, 65.0], d=[50.0] * 7)  # days_ago = 5

    assert "kd_golden_cross" not in names(detect_technical_signals(df))


def test_lookback_is_configurable():
    df = make_frame(k=[40.0, 60.0, 61.0, 62.0, 63.0, 64.0, 65.0], d=[50.0] * 7)  # days_ago = 5

    result = detect_technical_signals(df, signal_params=SignalParams(cross_lookback_days=6))

    assert find(result, "kd_golden_cross").days_ago == 5


def test_whipsaw_reports_both_crosses_in_order():
    df = make_frame(k=[40.0, 60.0, 45.0], d=[50.0, 50.0, 50.0])

    result = detect_technical_signals(df)

    crosses = [(s.name, s.days_ago) for s in result.signals if "cross" in s.name]
    assert crosses == [("kd_death_cross", 0), ("kd_golden_cross", 1)]


def test_touch_and_return_is_not_a_cross():
    # 下方 → 碰到（相等）→ 回到下方：不算交叉
    df = make_frame(k=[40.0, 50.0, 45.0], d=[50.0, 50.0, 50.0])

    assert not [n for n in names(detect_technical_signals(df)) if "kd_" in n and "cross" in n]


def test_cross_through_equal_day_counts_once():
    # 下方 → 相等 → 上方：在「上方」那天算一次黃金交叉
    df = make_frame(k=[40.0, 50.0, 60.0], d=[50.0, 50.0, 50.0])

    signal = find(detect_technical_signals(df), "kd_golden_cross")
    assert signal.days_ago == 0


@pytest.mark.parametrize("a, b, name", [
    ("ma5", "ma20", "ma5_ma20_golden_cross"),
    ("macd_dif", "macd_signal", "macd_golden_cross"),
    ("rsi6", "rsi12", "rsi6_rsi12_golden_cross"),
])
def test_other_golden_crosses(a, b, name):
    base = make_frame()[b].iloc[-1]
    result = detect_technical_signals(make_frame(**{a: [base - 1, base + 1], b: [base, base]}))

    assert find(result, name).bias == "bullish"


@pytest.mark.parametrize("a, b, name", [
    ("ma5", "ma20", "ma5_ma20_death_cross"),
    ("macd_dif", "macd_signal", "macd_death_cross"),
    ("rsi6", "rsi12", "rsi6_rsi12_death_cross"),
])
def test_other_death_crosses(a, b, name):
    base = make_frame()[b].iloc[-1]
    result = detect_technical_signals(make_frame(**{a: [base + 1, base - 1], b: [base, base]}))

    assert find(result, name).bias == "bearish"


# ---------------------------------------------------------------------------
# 最新交易日狀態
# ---------------------------------------------------------------------------

def test_ma_alignment():
    bull = detect_technical_signals(make_frame(ma5=[110.0], ma20=[105.0], ma60=[100.0]))
    bear = detect_technical_signals(make_frame(ma5=[90.0], ma20=[95.0], ma60=[100.0]))
    mixed = detect_technical_signals(make_frame(ma5=[110.0], ma20=[95.0], ma60=[100.0]))

    assert find(bull, "ma_bullish_alignment").bias == "bullish"
    assert find(bear, "ma_bearish_alignment").bias == "bearish"
    assert not [n for n in names(mixed) if "alignment" in n]


def test_price_vs_longest_ma():
    above = detect_technical_signals(make_frame(adj_close=[105.0], ma60=[100.0]))
    below = detect_technical_signals(make_frame(adj_close=[95.0], ma60=[100.0]))

    signal = find(above, "above_ma60")
    assert signal.bias == "bullish"
    assert signal.value == pytest.approx(105.0)
    assert signal.threshold == pytest.approx(100.0)
    assert find(below, "below_ma60").bias == "bearish"


@pytest.mark.parametrize("column, value, name, bias", [
    ("rsi6", 81.0, "rsi6_overbought", "bearish"),
    ("rsi6", 19.0, "rsi6_oversold", "bullish"),
    ("rsi12", 71.0, "rsi12_overbought", "bearish"),
    ("rsi12", 29.0, "rsi12_oversold", "bullish"),
    ("k", 81.0, "kd_overbought", "bearish"),
    ("k", 19.0, "kd_oversold", "bullish"),
])
def test_overbought_oversold(column, value, name, bias):
    # 只改最新一筆，且 d 跟著改避免觸發交叉
    overrides = {column: [value]}
    if column == "k":
        overrides["d"] = [value]
    if column == "rsi6":
        overrides["rsi12"] = [value]
    if column == "rsi12":
        overrides["rsi6"] = [value]
        if value > 50:
            overrides["rsi6"] = [79.0]  # 不觸發 rsi6 過熱
    result = detect_technical_signals(make_frame(**overrides))

    assert find(result, name).bias == bias


@pytest.mark.parametrize("overrides, name", [
    ({"rsi6": [80.0], "rsi12": [60.0]}, "rsi6_overbought"),
    ({"rsi6": [20.0], "rsi12": [40.0]}, "rsi6_oversold"),
    ({"rsi6": [70.0], "rsi12": [70.0]}, "rsi12_overbought"),
    ({"rsi6": [30.0], "rsi12": [30.0]}, "rsi12_oversold"),
    ({"k": [80.0], "d": [80.0]}, "kd_overbought"),
    ({"k": [20.0], "d": [20.0]}, "kd_oversold"),
])
def test_exact_threshold_does_not_trigger(overrides, name):
    result = detect_technical_signals(make_frame(**overrides))

    assert name not in names(result)


def test_macd_zero_line():
    above = detect_technical_signals(make_frame(macd_dif=[1.0], macd_signal=[1.0]))
    below = detect_technical_signals(make_frame(macd_dif=[-1.0], macd_signal=[-1.0]))

    assert find(above, "macd_above_zero").bias == "bullish"
    assert find(below, "macd_below_zero").bias == "bearish"


def test_bollinger_breaks_are_neutral():
    up = detect_technical_signals(make_frame(adj_close=[111.0], ma60=[111.0]))
    down = detect_technical_signals(make_frame(adj_close=[89.0], ma60=[89.0]))

    assert find(up, "bollinger_above_upper").bias == "neutral"
    assert find(down, "bollinger_below_lower").bias == "neutral"


def test_volume_ratio_uses_previous_day_20d_average():
    # 前一日20日均量1000，今天量2500 → 2.5倍爆量；今天的 vol_ma20 被拉高到1075不影響
    result = detect_technical_signals(make_frame(adj_volume=[1000.0, 2500.0], vol_ma20=[1000.0, 1075.0]))

    assert result.snapshot["volume_ratio"] == pytest.approx(2.5)
    signal = find(result, "volume_surge")
    assert signal.bias == "neutral"
    assert signal.value == pytest.approx(2.5)
    assert signal.threshold == pytest.approx(2.0)


def test_volume_shrink_and_configurable_ratio():
    df = make_frame(adj_volume=[1000.0, 400.0], vol_ma20=[1000.0, 970.0])

    assert "volume_shrink" in names(detect_technical_signals(df))
    assert "volume_shrink" not in names(
        detect_technical_signals(df, signal_params=SignalParams(volume_shrink_ratio=0.3))
    )


def test_signals_sorted_by_days_ago_then_name():
    df = make_frame(
        k=[40.0, 60.0, 61.0], d=[50.0, 50.0, 50.0],        # KD 黃金交叉 days_ago=1
        macd_dif=[1.0, 1.0, 1.0], macd_signal=[1.0, 1.0, 1.0],  # 今天 macd_above_zero
        adj_close=[100.0, 100.0, 105.0],                    # 今天 above_ma60
    )
    result = detect_technical_signals(df)

    keys = [(s.days_ago, s.name) for s in result.signals]
    assert keys == sorted(keys)
