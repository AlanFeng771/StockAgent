from __future__ import annotations

import pandas as pd
import pytest

from backend.app.signals.chip_signals import detect_chip_signals
from backend.app.signals.config import SignalParams

DATES = pd.bdate_range("2026-09-01", periods=10)


def make_institutional(foreign=None, trust=None, dealer=None, foreign_dealer=None, dates=DATES):
    """各參數為每日買賣超股數 list（對齊到最後 len 筆日期），未給的類別每天 0。"""
    n = len(dates)
    series = {
        "Foreign_Investor": foreign, "Investment_Trust": trust,
        "Dealer_Hedging": dealer, "Foreign_Dealer_Self": foreign_dealer,
    }
    rows = []
    for investor_type, values in series.items():
        values = [0] * n if values is None else [0] * (n - len(values)) + list(values)
        for day, net in zip(dates, values):
            rows.append({
                "date": day, "stock_id": "2330", "investor_type": investor_type,
                "buy": max(net, 0), "sell": max(-net, 0), "net": net,
            })
    return pd.DataFrame(rows)


def make_margin(margin_balance=None, short_balance=None, dates=DATES):
    n = len(dates)
    margin_balance = [1000] * n if margin_balance is None else [1000] * (n - len(margin_balance)) + list(margin_balance)
    short_balance = [10] * n if short_balance is None else [10] * (n - len(short_balance)) + list(short_balance)
    return pd.DataFrame({
        "date": dates, "stock_id": "2330",
        "margin_purchase_today_balance": margin_balance,
        "short_sale_today_balance": short_balance,
    })


def make_prices(adj_close=None, volume=None, dates=DATES):
    n = len(dates)
    adj_close = [100.0] * n if adj_close is None else [100.0] * (n - len(adj_close)) + list(adj_close)
    volume = [1_000_000] * n if volume is None else list(volume)
    return pd.DataFrame({"date": dates, "stock_id": "2330", "adj_close": adj_close, "volume": volume})


EMPTY_INSTITUTIONAL = make_institutional().iloc[0:0]
EMPTY_MARGIN = make_margin().iloc[0:0]


def detect(institutional=None, margin=None, prices=None, **params):
    return detect_chip_signals(
        make_institutional() if institutional is None else institutional,
        make_margin() if margin is None else margin,
        make_prices() if prices is None else prices,
        SignalParams(**params) if params else SignalParams(),
    )


def names(result):
    return [s.name for s in result.signals]


def find(result, name):
    matches = [s for s in result.signals if s.name == name]
    assert len(matches) == 1, f"{name}：{names(result)}"
    return matches[0]


# ---------------------------------------------------------------------------
# 基本行為
# ---------------------------------------------------------------------------

def test_both_empty_returns_none():
    assert detect(EMPTY_INSTITUTIONAL, EMPTY_MARGIN) is None


def test_neutral_data_has_no_signals():
    result = detect()

    assert result.signals == []
    assert result.as_of_institutional == DATES[-1].date()
    assert result.as_of_margin == DATES[-1].date()


def test_chip_dates_are_independent_from_prices():
    # 股價多一天（當天已收盤），籌碼資料還沒更新
    prices = make_prices(dates=pd.bdate_range("2026-09-01", periods=11))

    result = detect(prices=prices)

    assert result.as_of_institutional == DATES[-1].date()


def test_margin_only_still_produces_result():
    result = detect(institutional=EMPTY_INSTITUTIONAL)

    assert result.as_of_institutional is None
    assert result.snapshot["foreign_streak"] is None
    assert result.snapshot["margin_balance_lots"] == 1000


def test_unsorted_inputs_are_handled():
    institutional = make_institutional(foreign=[100, 100, 100]).sample(frac=1, random_state=0)

    assert "foreign_buy_streak" in names(detect(institutional=institutional))


# ---------------------------------------------------------------------------
# 法人分類與 snapshot
# ---------------------------------------------------------------------------

def test_foreign_includes_foreign_dealer_and_units_are_lots():
    institutional = make_institutional(foreign=[3000, 5000], foreign_dealer=[0, 1000], trust=[0, -2000], dealer=[0, 7000])

    snapshot = detect(institutional=institutional).snapshot

    assert snapshot["foreign_net_lots"] == pytest.approx(6.0)
    assert snapshot["trust_net_lots"] == pytest.approx(-2.0)
    assert snapshot["dealer_net_lots"] == pytest.approx(7.0)
    assert snapshot["foreign_net_5d_lots"] == pytest.approx(9.0)


def test_missing_investor_type_on_a_day_counts_as_zero():
    institutional = make_institutional(foreign=[1000] * 10)
    institutional = institutional[~((institutional["investor_type"] == "Investment_Trust")
                                    & (institutional["date"] == DATES[-1]))]

    assert detect(institutional=institutional).snapshot["trust_net_lots"] == 0


def test_foreign_trust_ratio_against_same_days_volume():
    institutional = make_institutional(foreign=[100_000] * 5, trust=[100_000] * 5)

    snapshot = detect(institutional=institutional).snapshot

    # (5 × 200,000) ÷ (5 × 1,000,000) = 20%
    assert snapshot["foreign_trust_net_5d_ratio_pct"] == pytest.approx(20.0)


def test_foreign_trust_ratio_none_when_volume_missing_for_a_day():
    prices = make_prices().iloc[:-1]  # 少了最新一天的成交量

    assert detect(prices=prices).snapshot["foreign_trust_net_5d_ratio_pct"] is None


# ---------------------------------------------------------------------------
# 連續買賣超
# ---------------------------------------------------------------------------

def test_foreign_buy_streak_reports_length_and_start_date():
    result = detect(institutional=make_institutional(foreign=[-5, 10, 20, 30, 40]))

    signal = find(result, "foreign_buy_streak")
    assert signal.bias == "bullish"
    assert signal.value == 4
    assert signal.threshold == 3
    assert signal.date == DATES[-4].date()
    assert signal.days_ago == 3
    assert result.snapshot["foreign_streak"] == 4


def test_trust_sell_streak():
    result = detect(institutional=make_institutional(trust=[5, -1, -1, -1]))

    signal = find(result, "trust_sell_streak")
    assert signal.bias == "bearish"
    assert result.snapshot["trust_streak"] == -3


def test_streak_below_threshold_no_signal():
    result = detect(institutional=make_institutional(foreign=[-5, 10, 20]))

    assert "foreign_buy_streak" not in names(result)
    assert result.snapshot["foreign_streak"] == 2


def test_zero_net_breaks_streak():
    result = detect(institutional=make_institutional(foreign=[10, 10, 10, 0]))

    assert result.snapshot["foreign_streak"] == 0
    assert "foreign_buy_streak" not in names(result)


def test_dealer_never_produces_signals():
    result = detect(institutional=make_institutional(dealer=[-1_000_000] * 10))

    assert not [n for n in names(result) if n.startswith("dealer")]


def test_streak_days_configurable():
    institutional = make_institutional(foreign=[-5, 10, 20])

    assert "foreign_buy_streak" in names(detect(institutional=institutional, chip_streak_days=2))


# ---------------------------------------------------------------------------
# 融資融券
# ---------------------------------------------------------------------------

def test_margin_up_price_down_is_bearish():
    margin = make_margin(margin_balance=[1000, 1010, 1020, 1030, 1040, 1060])  # +6%
    prices = make_prices(adj_close=[100.0, 99.0, 98.0, 97.0, 96.0, 95.0])     # −5%

    result = detect(margin=margin, prices=prices)

    signal = find(result, "margin_up_price_down")
    assert signal.bias == "bearish"
    assert result.snapshot["margin_change_5d_pct"] == pytest.approx(6.0)
    assert result.snapshot["price_change_5d_pct"] == pytest.approx(-5.0)


def test_margin_down_price_up_is_bullish():
    margin = make_margin(margin_balance=[1000, 990, 980, 970, 960, 940])  # −6%
    prices = make_prices(adj_close=[100.0, 101.0, 102.0, 103.0, 104.0, 105.0])

    assert find(detect(margin=margin, prices=prices), "margin_down_price_up").bias == "bullish"


def test_margin_and_price_same_direction_no_signal():
    margin = make_margin(margin_balance=[1000, 1060])
    prices = make_prices(adj_close=[100.0, 105.0])

    result = detect(margin=margin, prices=prices)

    assert not [n for n in names(result) if n.startswith("margin_")]


def test_margin_change_exactly_at_threshold_no_signal():
    margin = make_margin(margin_balance=[1000, 1010, 1020, 1030, 1040, 1050])  # 剛好 +5%
    prices = make_prices(adj_close=[100.0, 99.0, 98.0, 97.0, 96.0, 95.0])

    assert "margin_up_price_down" not in names(detect(margin=margin, prices=prices))


def test_price_change_aligned_to_margin_dates_not_latest_price():
    # 股價多一天大漲，但融資只到前一天：股價變化要用融資最新日對齊
    price_dates = pd.bdate_range("2026-09-01", periods=11)
    prices = make_prices(adj_close=[100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 200.0], dates=price_dates)
    margin = make_margin(margin_balance=[1000, 1010, 1020, 1030, 1040, 1060])

    result = detect(margin=margin, prices=prices)

    assert result.snapshot["price_change_5d_pct"] == pytest.approx(-5.0)
    assert "margin_up_price_down" in names(result)


def test_insufficient_margin_rows_gives_none():
    margin = make_margin(dates=DATES[-3:])

    assert detect(margin=margin).snapshot["margin_change_5d_pct"] is None


def test_high_short_margin_ratio_is_neutral():
    result = detect(margin=make_margin(margin_balance=[1000], short_balance=[350]))

    signal = find(result, "high_short_margin_ratio")
    assert signal.bias == "neutral"
    assert signal.value == pytest.approx(35.0)
    assert result.snapshot["short_margin_ratio_pct"] == pytest.approx(35.0)


def test_zero_margin_balance_ratio_is_none():
    result = detect(margin=make_margin(margin_balance=[0], short_balance=[10]))

    assert result.snapshot["short_margin_ratio_pct"] is None
    assert "high_short_margin_ratio" not in names(result)


def test_signals_sorted_by_days_ago_then_name():
    result = detect(
        institutional=make_institutional(foreign=[1, 1, 1], trust=[-1, -1, -1, -1]),
        margin=make_margin(margin_balance=[1000], short_balance=[400]),
    )

    keys = [(s.days_ago, s.name) for s in result.signals]
    assert keys == sorted(keys)
    assert len(keys) == 3


def test_short_margin_ratio_exactly_at_threshold_no_signal():
    # 280 / 1000 × 100 直接算會得到 28.000000000000004，不可被判成超過 28% 門檻
    result = detect(margin=make_margin(margin_balance=[1000], short_balance=[280]), short_margin_ratio_pct=28.0)

    assert result.snapshot["short_margin_ratio_pct"] == 28.0
    assert "high_short_margin_ratio" not in names(result)
