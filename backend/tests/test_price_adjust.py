from __future__ import annotations

import pandas as pd
import pytest

from backend.app.indicators.price_adjust import adjust_prices

ADJ_COLUMNS = ["adj_factor", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume"]


def make_prices(rows, stock_id="0056"):
    """rows: [(date, close, volume)]，open/high/low 以 close 為基準方便驗算。"""
    return pd.DataFrame([
        {
            "date": pd.Timestamp(d), "stock_id": stock_id,
            "open": c, "high": c + 1, "low": c - 1, "close": c,
            "volume": v, "trading_money": 0, "turnover": 0,
        }
        for d, c, v in rows
    ])


def make_dividends(rows, stock_id="0056"):
    """rows: [(date, before_price, reference_price)]"""
    return pd.DataFrame(
        [{"date": pd.Timestamp(d), "stock_id": stock_id, "before_price": b,
          "reference_price": r, "dividend": b - r, "dividend_type": "息"} for d, b, r in rows],
        columns=["date", "stock_id", "before_price", "reference_price", "dividend", "dividend_type"],
    )


def make_splits(rows):
    """rows: [(date, stock_id, before_price, after_price)]"""
    return pd.DataFrame(
        [{"date": pd.Timestamp(d), "stock_id": s, "type": "面額變更",
          "before_price": b, "after_price": a} for d, s, b, a in rows],
        columns=["date", "stock_id", "type", "before_price", "after_price"],
    )


NO_DIVIDENDS = make_dividends([])
NO_SPLITS = make_splits([])


# ---------------------------------------------------------------------------
# 無事件
# ---------------------------------------------------------------------------

def test_no_events_adjusted_equals_raw():
    prices = make_prices([("2026-07-17", 49.0, 100), ("2026-07-20", 49.95, 200)])

    df = adjust_prices(prices, NO_DIVIDENDS, NO_SPLITS)

    assert list(df["adj_factor"]) == [1.0, 1.0]
    assert list(df["adj_close"]) == list(df["close"])
    assert list(df["adj_volume"]) == list(df["volume"])


def test_output_keeps_original_columns_sorted_by_date():
    prices = make_prices([("2026-07-20", 49.95, 200), ("2026-07-17", 49.0, 100)])

    df = adjust_prices(prices, NO_DIVIDENDS, NO_SPLITS)

    assert list(df.columns) == list(prices.columns) + ADJ_COLUMNS
    assert list(df["date"]) == [pd.Timestamp("2026-07-17"), pd.Timestamp("2026-07-20")]
    assert list(df.index) == [0, 1]


def test_empty_prices_returns_empty_with_all_columns():
    prices = make_prices([]).reindex(columns=[
        "date", "stock_id", "open", "high", "low", "close", "volume", "trading_money", "turnover",
    ])

    df = adjust_prices(prices, NO_DIVIDENDS, NO_SPLITS)

    assert df.empty
    assert list(df.columns) == list(prices.columns) + ADJ_COLUMNS


# ---------------------------------------------------------------------------
# 除權息（真實案例：0056 2026-07-21 除息 1.35，前收49.95，參考價48.60）
# ---------------------------------------------------------------------------

def test_dividend_adjusts_prices_before_event_only():
    prices = make_prices([
        ("2026-07-17", 49.00, 100),
        ("2026-07-20", 49.95, 200),
        ("2026-07-21", 49.55, 300),  # 除息日
        ("2026-07-22", 49.80, 400),
    ])
    dividends = make_dividends([("2026-07-21", 49.95, 48.60)])
    factor = 48.60 / 49.95

    df = adjust_prices(prices, dividends, NO_SPLITS)

    assert df["adj_factor"].tolist() == pytest.approx([factor, factor, 1.0, 1.0])
    assert df["adj_close"].tolist() == pytest.approx([49.00 * factor, 48.60, 49.55, 49.80])
    assert df["adj_high"].iloc[0] == pytest.approx(50.00 * factor)
    assert df["adj_low"].iloc[0] == pytest.approx(48.00 * factor)
    # 除息不改變股數，成交量不調整
    assert df["adj_volume"].tolist() == [100, 200, 300, 400]


def test_latest_row_always_equals_raw():
    prices = make_prices([("2026-07-20", 49.95, 200), ("2026-07-21", 49.55, 300)])
    dividends = make_dividends([("2026-07-21", 49.95, 48.60)])

    df = adjust_prices(prices, dividends, NO_SPLITS)

    last = df.iloc[-1]
    assert last["adj_close"] == last["close"]
    assert last["adj_open"] == last["open"]
    assert last["adj_volume"] == last["volume"]


def test_multiple_events_multiply_cumulatively():
    prices = make_prices([
        ("2026-04-22", 42.00, 1),
        ("2026-04-23", 41.70, 1),  # 第一次除息
        ("2026-07-20", 49.95, 1),
        ("2026-07-21", 49.55, 1),  # 第二次除息
    ])
    dividends = make_dividends([("2026-04-23", 42.61, 41.61), ("2026-07-21", 49.95, 48.60)])
    f1, f2 = 41.61 / 42.61, 48.60 / 49.95

    df = adjust_prices(prices, dividends, NO_SPLITS)

    assert df["adj_factor"].tolist() == pytest.approx([f1 * f2, f2, f2, 1.0])


# ---------------------------------------------------------------------------
# 面額變更/分割（真實案例：6763 2024-09-09 491 → 49.1，停牌期間 08-28 之後無交易）
# ---------------------------------------------------------------------------

def test_split_adjusts_price_and_volume_and_filters_other_stocks():
    prices = make_prices([
        ("2024-08-27", 480.0, 100_000),
        ("2024-08-28", 491.0, 136_558),
        ("2024-09-09", 46.6, 2_318_221),  # 分割後恢復交易
    ], stock_id="6763")
    splits = make_splits([
        ("2024-09-09", "6763", 491.0, 49.1),
        ("2024-09-09", "8932", 169.5, 84.75),  # 全市場資料，其他股票要被濾掉
    ])

    df = adjust_prices(prices, NO_DIVIDENDS, splits)

    assert df["adj_factor"].tolist() == pytest.approx([0.1, 0.1, 1.0])
    assert df["adj_close"].tolist() == pytest.approx([48.0, 49.1, 46.6])
    assert df["adj_volume"].tolist() == pytest.approx([1_000_000, 1_365_580, 2_318_221])


def test_dividend_and_split_combine():
    prices = make_prices([
        ("2024-08-01", 100.0, 10),
        ("2024-08-02", 100.0, 10),  # 除息 100 → 95
        ("2024-09-09", 9.5, 100),   # 分割 95 → 9.5
    ], stock_id="6763")
    dividends = make_dividends([("2024-08-02", 100.0, 95.0)], stock_id="6763")
    splits = make_splits([("2024-09-09", "6763", 95.0, 9.5)])

    df = adjust_prices(prices, dividends, splits)

    assert df["adj_factor"].tolist() == pytest.approx([0.095, 0.1, 1.0])
    # 成交量只受分割影響
    assert df["adj_volume"].tolist() == pytest.approx([100, 100, 100])


# ---------------------------------------------------------------------------
# 事件範圍與無效事件
# ---------------------------------------------------------------------------

def test_events_outside_price_range_are_ignored():
    prices = make_prices([("2026-07-20", 49.95, 200), ("2026-07-21", 49.55, 300)])
    dividends = make_dividends([
        ("2026-01-22", 38.21, 37.34),  # 早於第一筆股價：沒有需要調整的列
        ("2026-10-23", 50.00, 49.00),  # 晚於最後一筆股價：忽略，否則最新價會被改動
    ])

    df = adjust_prices(prices, dividends, NO_SPLITS)

    assert df["adj_factor"].tolist() == [1.0, 1.0]


def test_event_on_last_price_date_is_applied():
    prices = make_prices([("2026-07-20", 49.95, 200), ("2026-07-21", 49.55, 300)])
    dividends = make_dividends([("2026-07-21", 49.95, 48.60)])

    df = adjust_prices(prices, dividends, NO_SPLITS)

    assert df["adj_factor"].iloc[0] == pytest.approx(48.60 / 49.95)


def test_events_of_other_stocks_in_dividends_are_ignored():
    prices = make_prices([("2026-07-20", 49.95, 200), ("2026-07-21", 49.55, 300)])
    dividends = make_dividends([("2026-07-21", 49.95, 48.60)], stock_id="2330")

    df = adjust_prices(prices, dividends, NO_SPLITS)

    assert df["adj_factor"].tolist() == [1.0, 1.0]


@pytest.mark.parametrize("before, reference", [(0.0, 48.6), (49.95, 0.0), (49.95, float("nan")), (-1.0, 48.6)])
def test_invalid_events_are_ignored(before, reference):
    prices = make_prices([("2026-07-20", 49.95, 200), ("2026-07-21", 49.55, 300)])
    dividends = make_dividends([("2026-07-21", before, reference)])

    df = adjust_prices(prices, dividends, NO_SPLITS)

    assert df["adj_factor"].tolist() == [1.0, 1.0]


def test_does_not_mutate_input():
    prices = make_prices([("2026-07-21", 49.55, 300), ("2026-07-20", 49.95, 200)])
    snapshot = prices.copy()

    adjust_prices(prices, make_dividends([("2026-07-21", 49.95, 48.60)]), NO_SPLITS)

    pd.testing.assert_frame_equal(prices, snapshot)
