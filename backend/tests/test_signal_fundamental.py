from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.app.signals.config import SignalParams
from backend.app.signals.fundamental_signals import detect_fundamental_signals

# ---------------------------------------------------------------------------
# 測試資料建構
# ---------------------------------------------------------------------------


def make_revenue(values, end_year=2026, end_month=8):
    """values：依時間順序的月營收，最後一筆是 end_year/end_month。
    date 依真實API格式設為「公布月份」＝營收月份的下個月 1 日。"""
    periods = pd.period_range(end=pd.Period(year=end_year, month=end_month, freq="M"), periods=len(values))
    return pd.DataFrame([
        {
            "date": (p + 1).to_timestamp(), "stock_id": "2330", "country": "Taiwan",
            "revenue": v, "revenue_month": p.month, "revenue_year": p.year, "create_time": "",
        }
        for p, v in zip(periods, values)
    ], columns=["date", "stock_id", "country", "revenue", "revenue_month", "revenue_year", "create_time"])


def growing_revenue(months=15, yoy=0.10, base=100.0):
    """每個月都比去年同月成長 yoy，且每月營收不同（避免剛好創新高等巧合）。"""
    values = [base + i for i in range(12)]
    while len(values) < months:
        values.append(values[-12] * (1 + yoy))
    return values[-months:]


# 2330 真實單季 EPS（2024Q2 ~ 2026Q2）
REAL_EPS = {
    "2024-06-30": 9.56, "2024-09-30": 12.55, "2024-12-31": 14.45, "2025-03-31": 13.95,
    "2025-06-30": 15.36, "2025-09-30": 17.44, "2025-12-31": 19.51, "2026-03-31": 22.08,
    "2026-06-30": 27.25,
}


def make_financials(eps=None, gross_margin=None, revenue=1000.0, operating_margin=0.4):
    """eps：{季底日: EPS}；gross_margin：{季底日: 毛利率(0~1)}，未給則一律 0.5。"""
    eps = REAL_EPS if eps is None else eps
    rows = []
    for quarter, value in eps.items():
        gm = 0.5 if gross_margin is None else gross_margin.get(quarter, 0.5)
        for type_, v in [
            ("EPS", value), ("Revenue", revenue), ("GrossProfit", revenue * gm),
            ("OperatingIncome", revenue * operating_margin),
        ]:
            rows.append({"date": pd.Timestamp(quarter), "stock_id": "2330", "type": type_, "value": v, "origin_name": ""})
    return pd.DataFrame(rows, columns=["date", "stock_id", "type", "value", "origin_name"])


def make_valuation(pe_values, end="2026-09-30", pb=10.0, dividend_yield=1.0):
    dates = pd.bdate_range(end=end, periods=len(pe_values))
    return pd.DataFrame({
        "date": dates, "stock_id": "2330", "pe_ratio": pe_values,
        "pb_ratio": pb, "dividend_yield": dividend_yield,
    })


EMPTY_REVENUE = make_revenue([])
EMPTY_FINANCIALS = make_financials(eps={})
EMPTY_VALUATION = make_valuation([])
NEUTRAL_PE = [20.0 + (i % 10) for i in range(245)]  # 今天=24，落在近一年中段（約40百分位）


def detect(revenue=None, financials=None, valuation=None, **params):
    return detect_fundamental_signals(
        make_revenue(growing_revenue()) if revenue is None else revenue,
        make_financials() if financials is None else financials,
        make_valuation(NEUTRAL_PE) if valuation is None else valuation,
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

def test_all_empty_returns_none():
    assert detect(EMPTY_REVENUE, EMPTY_FINANCIALS, EMPTY_VALUATION) is None


def test_etf_like_only_valuation_still_returns_result():
    result = detect(EMPTY_REVENUE, EMPTY_FINANCIALS)

    assert result.as_of_revenue is None
    assert result.as_of_financials is None
    assert result.snapshot["revenue_yoy_pct"] is None
    assert result.snapshot["eps"] is None
    assert result.snapshot["pe_ratio"] == NEUTRAL_PE[-1]


def test_as_of_dates_per_source():
    result = detect()

    assert result.as_of_revenue == date(2026, 8, 1)
    assert result.as_of_financials == date(2026, 6, 30)
    assert result.as_of_valuation == date(2026, 9, 30)


# ---------------------------------------------------------------------------
# 月營收
# ---------------------------------------------------------------------------

def test_revenue_period_uses_revenue_year_month_not_date():
    # 最新一期是 2025 年 12 月（date 是 2026-01-01），去年同月是 2024 年 12 月
    values = growing_revenue(months=13, yoy=0.30)
    result = detect(revenue=make_revenue(values, end_year=2025, end_month=12))

    assert result.as_of_revenue == date(2025, 12, 1)
    assert result.snapshot["revenue_yoy_pct"] == pytest.approx(30.0)


def test_revenue_yoy_growth_signal():
    result = detect(revenue=make_revenue(growing_revenue(yoy=0.25)))

    signal = find(result, "revenue_yoy_growth")
    assert signal.bias == "bullish"
    assert signal.value == pytest.approx(25.0)
    assert signal.threshold == 20.0
    assert signal.date == date(2026, 8, 1)


def test_revenue_yoy_decline_signal():
    result = detect(revenue=make_revenue(growing_revenue(yoy=-0.15)))

    assert find(result, "revenue_yoy_decline").bias == "bearish"


def test_revenue_yoy_exactly_at_threshold_no_signal():
    # 去年同月 100 → 今年 120，剛好 +20%
    values = [100.0] + [300.0 + i for i in range(11)] + [120.0]

    result = detect(revenue=make_revenue(values))

    assert result.snapshot["revenue_yoy_pct"] == 20.0
    assert "revenue_yoy_growth" not in names(result)


def test_revenue_missing_last_year_month_gives_none():
    result = detect(revenue=make_revenue(growing_revenue(months=12)))

    assert result.snapshot["revenue_yoy_pct"] is None
    assert not [n for n in names(result) if n.startswith("revenue_yoy")]


def test_revenue_mom():
    values = growing_revenue(months=15)
    values[-1] = values[-2] * 1.05
    result = detect(revenue=make_revenue(values))

    assert result.snapshot["revenue_mom_pct"] == pytest.approx(5.0)


def test_revenue_growth_streak():
    result = detect(revenue=make_revenue(growing_revenue(months=15, yoy=0.10)))

    signal = find(result, "revenue_growth_streak")
    assert signal.bias == "bullish"
    assert signal.value == 3  # 15 個月資料只算得出最近 3 個月的年增率
    assert signal.date == date(2026, 6, 1)
    assert signal.days_ago == 2
    assert result.snapshot["revenue_yoy_streak"] == 3


def test_revenue_decline_streak_and_broken_streak():
    declining = detect(revenue=make_revenue(growing_revenue(yoy=-0.05)))
    values = growing_revenue(yoy=0.10)
    values[-2] = values[-14] * 0.9  # 倒數第2個月年增率轉負
    broken = detect(revenue=make_revenue(values))

    assert find(declining, "revenue_decline_streak").bias == "bearish"
    assert declining.snapshot["revenue_yoy_streak"] == -3
    assert broken.snapshot["revenue_yoy_streak"] == 1
    assert "revenue_growth_streak" not in names(broken)


def test_revenue_12m_high():
    values = growing_revenue(months=15)
    values[-1] = max(values) + 50
    high = detect(revenue=make_revenue(values))
    values[-1] = max(values[-12:-1])  # 與前高相等不算創新高
    equal = detect(revenue=make_revenue(values))

    assert find(high, "revenue_12m_high").bias == "bullish"
    assert "revenue_12m_high" not in names(equal)


def test_duplicate_revenue_period_keeps_last():
    revenue = make_revenue(growing_revenue(yoy=0.25))
    duplicate = revenue.iloc[[-1]].assign(revenue=revenue["revenue"].iloc[-13] * 1.5)

    result = detect(revenue=pd.concat([revenue, duplicate]))

    assert result.snapshot["revenue_yoy_pct"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# 財報
# ---------------------------------------------------------------------------

def test_real_eps_values():
    snapshot = detect().snapshot

    assert snapshot["eps"] == 27.25
    # 2026Q2 27.25 對 2025Q2 15.36
    assert snapshot["eps_yoy_pct"] == pytest.approx((27.25 - 15.36) / 15.36 * 100)
    assert snapshot["ttm_eps"] == pytest.approx(17.44 + 19.51 + 22.08 + 27.25)


def test_eps_yoy_growth_signal():
    signal = find(detect(), "eps_yoy_growth")

    assert signal.bias == "bullish"
    assert signal.date == date(2026, 6, 30)
    assert signal.category == "fundamental"


def test_eps_negative_and_yoy_none_when_last_year_not_positive():
    eps = {"2025-06-30": -1.0, "2025-09-30": 1.0, "2025-12-31": 1.0, "2026-03-31": 1.0, "2026-06-30": -0.5}

    result = detect(financials=make_financials(eps=eps))

    assert find(result, "eps_negative").bias == "bearish"
    assert result.snapshot["eps_yoy_pct"] is None


def test_ttm_eps_requires_four_consecutive_quarters():
    eps = {"2025-06-30": 1.0, "2025-12-31": 1.0, "2026-03-31": 1.0, "2026-06-30": 1.0}  # 缺 2025Q3

    assert detect(financials=make_financials(eps=eps)).snapshot["ttm_eps"] is None


def test_gross_margin_change():
    up = detect(financials=make_financials(gross_margin={"2025-06-30": 0.50, "2026-06-30": 0.53}))
    down = detect(financials=make_financials(gross_margin={"2025-06-30": 0.50, "2026-06-30": 0.47}))
    flat = detect(financials=make_financials(gross_margin={"2025-06-30": 0.50, "2026-06-30": 0.52}))

    assert up.snapshot["gross_margin_pct"] == pytest.approx(53.0)
    assert up.snapshot["gross_margin_change_pp"] == pytest.approx(3.0)
    assert find(up, "gross_margin_up").bias == "bullish"
    assert find(down, "gross_margin_down").bias == "bearish"
    assert flat.snapshot["gross_margin_change_pp"] == 2.0
    assert not [n for n in names(flat) if n.startswith("gross_margin")]


def test_operating_margin():
    assert detect().snapshot["operating_margin_pct"] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# 估值
# ---------------------------------------------------------------------------

def test_valuation_snapshot():
    snapshot = detect(valuation=make_valuation(NEUTRAL_PE, pb=9.5, dividend_yield=1.2)).snapshot

    assert snapshot["pb_ratio"] == 9.5
    assert snapshot["dividend_yield"] == 1.2


def test_pe_low_and_high():
    low = detect(valuation=make_valuation([30.0] * 100 + [10.0]))
    high = detect(valuation=make_valuation([10.0] * 100 + [30.0]))

    assert low.snapshot["pe_percentile"] == 0.0
    assert find(low, "pe_low").bias == "bullish"
    assert high.snapshot["pe_percentile"] == 100.0
    assert find(high, "pe_high").bias == "bearish"


def test_pe_percentile_ignores_non_positive_and_requires_min_days():
    with_losses = make_valuation([0.0] * 100 + [10.0] * 100 + [30.0])
    too_short = make_valuation([10.0] * 30 + [30.0])
    loss_today = make_valuation([10.0] * 100 + [0.0])

    assert detect(valuation=with_losses).snapshot["pe_percentile"] == 100.0
    assert detect(valuation=too_short).snapshot["pe_percentile"] is None
    assert detect(valuation=loss_today).snapshot["pe_percentile"] is None


def test_signals_sorted():
    result = detect(
        revenue=make_revenue(growing_revenue(yoy=0.25)),
        valuation=make_valuation([30.0] * 100 + [10.0]),
    )

    keys = [(s.days_ago, s.name) for s in result.signals]
    assert keys == sorted(keys)


def test_streak_reaching_data_limit_is_marked_as_at_least():
    # 15 個月資料只算得出 3 個月年增率，且 3 個月都成長 → 實際可能更長，要標示「至少」
    capped = detect(revenue=make_revenue(growing_revenue(months=15, yoy=0.10)))
    values = growing_revenue(months=16, yoy=0.10)
    values[-4] = values[-16] * 0.9  # 最早可算的那個月年增率為負，連續區間在資料範圍內結束
    bounded = detect(revenue=make_revenue(values))

    assert capped.snapshot["revenue_yoy_streak_capped"] == 1.0
    assert "至少" in find(capped, "revenue_growth_streak").description
    assert bounded.snapshot["revenue_yoy_streak_capped"] == 0.0
    assert "至少" not in find(bounded, "revenue_growth_streak").description
