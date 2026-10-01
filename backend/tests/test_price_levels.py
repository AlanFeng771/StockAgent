from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from backend.app.signals.price_levels import build_price_levels

N = 65
DATES = pd.bdate_range(end="2026-08-14", periods=N)
NO_DIVIDENDS = pd.DataFrame(columns=["date", "stock_id", "before_price", "reference_price", "dividend", "dividend_type"])
NO_SPLITS = pd.DataFrame(columns=["date", "stock_id", "type", "before_price", "after_price"])


def make_df(close=None, high=None, low=None, factor=None, **indicators):
    """原始價 + 調整係數 → 組出 compute_technical 格式。未給的均線/布林放在遠離現價處避免干擾。"""
    close = np.full(N, 50.0) if close is None else np.asarray(close, dtype=float)
    high = close + 0.5 if high is None else np.asarray(high, dtype=float)
    low = close - 0.5 if low is None else np.asarray(low, dtype=float)
    factor = np.ones(N) if factor is None else np.asarray(factor, dtype=float)
    df = pd.DataFrame({
        "date": DATES, "stock_id": "0056",
        "open": close, "high": high, "low": low, "close": close, "volume": 1000,
        "adj_factor": factor,
        "adj_open": close * factor, "adj_high": high * factor, "adj_low": low * factor,
        "adj_close": close * factor, "adj_volume": 1000.0,
    })
    defaults = {"ma5": 10.0, "ma20": 10.0, "ma60": 10.0, "bb_upper": 1000.0, "bb_lower": 10.0, "atr": np.nan}
    for column, value in {**defaults, **indicators}.items():
        df[column] = value
    return df


def dividends(*rows):
    """rows: (date, before_price, reference_price)"""
    return pd.DataFrame(
        [{"date": pd.Timestamp(d), "stock_id": "0056", "before_price": b, "reference_price": r,
          "dividend": round(b - r, 4), "dividend_type": "息"} for d, b, r in rows],
        columns=NO_DIVIDENDS.columns,
    )


def splits(*rows):
    return pd.DataFrame(
        [{"date": pd.Timestamp(d), "stock_id": "0056", "type": "面額變更", "before_price": b, "after_price": a}
         for d, b, a in rows],
        columns=NO_SPLITS.columns,
    )


def build(df, divs=NO_DIVIDENDS, spl=NO_SPLITS, kind="fund"):
    return build_price_levels(df, divs, spl, kind)


def by_source(levels, source):
    matches = [lv for lv in levels if source in lv.source]
    assert len(matches) == 1, [lv.source for lv in levels]
    return matches[0]


# ---------------------------------------------------------------------------
# 分類、排序、距離
# ---------------------------------------------------------------------------

def test_indicators_classified_and_sorted_nearest_first():
    result = build(make_df(ma5=50.6, ma20=49.0, ma60=48.0, bb_upper=53.0, bb_lower=46.0))

    assert result.close == 50.0
    assert [lv.source for lv in result.supports][:4] == ["20日最低、60日最低", "MA20", "MA60", "布林下軌"]
    assert [lv.source for lv in result.resistances][:2] == ["20日最高、60日最高", "MA5"]
    ma20 = by_source(result.supports, "MA20")
    assert ma20.date is None
    assert ma20.chart_price is None
    assert ma20.distance_pct == pytest.approx(-2.0)


def test_level_equal_to_close_is_excluded():
    result = build(make_df(ma5=50.0))

    assert all(lv.source != "MA5" for lv in result.supports + result.resistances)


def test_prices_aligned_to_tick():
    result = build(make_df(ma20=49.123), kind="fund")
    stock = build(make_df(close=np.full(N, 2510.0), ma20=2173.59), kind="stock")

    assert by_source(result.supports, "MA20").price == 49.12
    assert by_source(result.supports, "MA20").adjusted_price == pytest.approx(49.123)
    assert by_source(stock.supports, "MA20").price == 2170.0  # 支撐無條件捨去


# ---------------------------------------------------------------------------
# 近期高低點：日期、合併、新高旗標
# ---------------------------------------------------------------------------

def test_extremes_carry_date_and_merge_when_identical():
    high = np.full(N, 50.5)
    high[-10] = 55.0  # 20 日與 60 日的最高都在倒數第10天
    result = build(make_df(high=high))

    level = by_source(result.resistances, "最高")
    assert level.source == "20日最高、60日最高"
    assert level.date == DATES[-10].date()


def test_separate_extremes_for_each_window():
    high = np.full(N, 50.5)
    high[-30] = 56.0  # 只在 60 日視窗內
    high[-5] = 54.0
    result = build(make_df(high=high))

    assert by_source(result.resistances, "20日最高").price == 54.0
    assert by_source(result.resistances, "60日最高").price == 56.0


def test_ties_take_most_recent_date():
    high = np.full(N, 50.5)
    high[-15] = high[-3] = 55.0
    result = build(make_df(high=high))

    assert by_source(result.resistances, "最高").date == DATES[-3].date()


def test_new_high_flags():
    high = np.full(N, 50.5)
    high[-1] = 52.0  # 今天盤中創新高、收在 50
    low = np.full(N, 49.5)
    low[-1] = 49.8   # 今天低點高於近期低點
    result = build(make_df(high=high, low=low))

    assert result.flags["new_high_20d"] is True
    assert result.flags["new_high_60d"] is True
    assert result.flags["new_low_20d"] is False
    assert by_source(result.resistances, "最高").date == DATES[-1].date()


# ---------------------------------------------------------------------------
# 除權息前的價位：還原價 ～ 看盤軟體原始價 區間
# ---------------------------------------------------------------------------

def test_level_before_dividend_has_chart_price_zone():
    # 重現 0056：06-23 原始高 54.90，07-21 除息（前收 49.95 → 參考價 48.60），之後最高 54.00
    ex_index = N - 18
    factor = np.where(np.arange(N) < ex_index, 48.60 / 49.95, 1.0)
    close = np.full(N, 53.40)
    high = np.full(N, 53.5)
    high[ex_index - 20] = 54.90
    high[-1] = 54.00
    result = build(make_df(close=close, high=high, factor=factor),
                   divs=dividends((DATES[ex_index], 49.95, 48.60)))

    top = by_source(result.resistances, "20日最高")
    assert top.price == 54.00 and top.chart_price is None and top.date == DATES[-1].date()
    assert result.flags["new_high_60d"] is True
    # 06-23 那天換算後 53.42，不再是 60 日最高；60 日最高也是今天
    assert by_source(result.resistances, "60日最高").price == 54.00


def test_older_high_before_dividend_keeps_zone():
    ex_index = N - 18
    factor = np.where(np.arange(N) < ex_index, 0.95, 1.0)
    close = np.full(N, 50.0)
    high = np.full(N, 50.5)
    high[ex_index - 20] = 60.0  # 還原後 57.0，仍是最高
    result = build(make_df(close=close, high=high, factor=factor),
                   divs=dividends((DATES[ex_index], 52.0, 49.4)))

    level = by_source(result.resistances, "60日最高")
    assert level.price == 57.0
    assert level.chart_price == 60.0
    assert level.date == DATES[ex_index - 20].date()


def test_split_after_level_drops_chart_price():
    split_index = N - 10
    factor = np.where(np.arange(N) < split_index, 0.1, 1.0)
    close = np.where(np.arange(N) < split_index, 500.0, 50.0)
    high = close + 1
    high[split_index - 5] = 560.0  # 還原後 56
    result = build(make_df(close=close, high=high, factor=factor), spl=splits((DATES[split_index], 500.0, 50.0)),
                   kind="stock")

    level = by_source(result.resistances, "60日最高")
    assert level.price == 56.0
    assert level.chart_price is None


# ---------------------------------------------------------------------------
# 填息價
# ---------------------------------------------------------------------------

def test_fill_gap_filled_on_first_close_at_or_above_before_price():
    ex_index = N - 10
    close = np.full(N, 49.0)
    close[ex_index:] = [48.6, 49.2, 49.95, 50.5, 49.0, 50.0, 50.0, 50.0, 50.0, 50.0]
    result = build(make_df(close=close), divs=dividends((DATES[ex_index], 49.95, 48.60)))

    gap = result.fill_gap
    assert gap.ex_date == DATES[ex_index].date()
    assert gap.fill_price == 49.95
    assert gap.dividend == pytest.approx(1.35)
    assert gap.filled is True
    assert gap.filled_date == DATES[ex_index + 2].date()


def test_fill_gap_not_yet_filled():
    ex_index = N - 5
    close = np.full(N, 49.0)
    close[ex_index:] = 48.7
    result = build(make_df(close=close), divs=dividends((DATES[ex_index], 49.95, 48.60)))

    assert result.fill_gap.filled is False
    assert result.fill_gap.filled_date is None


def test_fill_gap_uses_latest_dividend_in_range_and_ignores_outside():
    close = np.full(N, 49.0)
    result = build(make_df(close=close), divs=dividends(
        ("2025-01-02", 40.0, 39.0),                   # 股價區間之前
        (DATES[10], 49.5, 48.5),
        (DATES[40], 49.9, 48.9),                      # 最近一次
        ("2026-12-01", 60.0, 59.0),                   # 未來（晚於最新股價）
    ))

    assert result.fill_gap.ex_date == DATES[40].date()


def test_no_dividend_no_fill_gap():
    assert build(make_df()).fill_gap is None


def test_split_after_dividend_drops_fill_gap():
    result = build(make_df(), divs=dividends((DATES[20], 49.95, 48.6)), spl=splits((DATES[30], 50.0, 5.0)))

    assert result.fill_gap is None


def test_tick_rounding_never_crosses_current_price():
    # 實測問題：現價 110.85、支撐還原價 110.84，四捨五入到 0.5 會變成 111.0（高於現價）
    close = np.full(N, 110.85)
    result = build(make_df(close=close, ma20=110.84, ma5=110.86), kind="stock")

    support = by_source(result.supports, "MA20")
    resistance = by_source(result.resistances, "MA5")
    assert support.price == 110.5
    assert resistance.price == 111.0
    assert all(lv.price <= result.close for lv in result.supports)
    assert all(lv.price >= result.close for lv in result.resistances)



# ---------------------------------------------------------------------------
# ATR 推算價位（2026-10-01：2330 創新高時上方只剩布林上軌一個價位，買點/賣點/目標價全落在同一價）
# ---------------------------------------------------------------------------

def test_atr_projection_levels_above_and_below_close():
    result = build(make_df(atr=1.2), kind="fund")

    up1 = by_source(result.resistances, "現價+1×ATR")
    up2 = by_source(result.resistances, "現價+2×ATR")
    down1 = by_source(result.supports, "現價-1×ATR")
    down2 = by_source(result.supports, "現價-2×ATR")
    assert (up1.price, up2.price, down1.price, down2.price) == (51.2, 52.4, 48.8, 47.6)
    assert {up1.category, down2.category} == {"atr_projection"}
    assert up1.date is None and up1.chart_price is None


def test_level_categories():
    high = np.full(N, 50.5)
    high[-10] = 55.0
    result = build(make_df(high=high, ma20=49.0, atr=1.0))

    assert by_source(result.resistances, "最高").category == "high_low"
    assert by_source(result.supports, "MA20").category == "indicator"


def test_atr_projection_tick_rounding_direction():
    # 現價 2510、ATR 37 → 上方 2547 進位到 2550、下方 2473 捨去到 2470（1000 元以上級距 5）
    result = build(make_df(close=np.full(N, 2510.0), atr=37.0), kind="stock")

    assert by_source(result.resistances, "現價+1×ATR").price == 2550.0
    assert by_source(result.supports, "現價-1×ATR").price == 2470.0


def test_no_atr_projection_when_atr_missing():
    result = build(make_df())

    assert not [lv for lv in result.supports + result.resistances if lv.category == "atr_projection"]
