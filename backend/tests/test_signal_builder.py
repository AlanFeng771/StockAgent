from __future__ import annotations

import json
from datetime import date

import numpy as np
import pandas as pd

from backend.app.data_sources import finmind_client as fc
from backend.app.signals.config import TECHNICAL, SignalParams
from backend.app.signals.signal_builder import FRESHNESS_KEYS, StockRawData, build_stock_signals

PRICE_DAYS = pd.bdate_range(end="2026-10-01", periods=TECHNICAL.required_price_rows() + 10)
CHIP_DAYS = PRICE_DAYS[-11:-1]  # 籌碼比股價晚一天


def empty(columns):
    return pd.DataFrame(columns=columns)


def make_prices(days=PRICE_DAYS):
    closes = 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, len(days)))
    return pd.DataFrame({
        "date": days, "stock_id": "2330", "open": closes, "high": closes + 1, "low": closes - 1,
        "close": closes, "volume": 1_000_000, "trading_money": 0, "turnover": 0,
    })


def make_institutional():
    return pd.DataFrame([
        {"date": d, "stock_id": "2330", "investor_type": t, "buy": 100, "sell": 0, "net": 100}
        for d in CHIP_DAYS for t in ("Foreign_Investor", "Investment_Trust")
    ])


def make_margin():
    return pd.DataFrame({
        "date": CHIP_DAYS, "stock_id": "2330",
        "margin_purchase_today_balance": 1000, "short_sale_today_balance": 10,
    })


def make_revenue():
    periods = pd.period_range(end="2026-08", periods=15, freq="M")
    return pd.DataFrame({
        "date": [(p + 1).to_timestamp() for p in periods], "stock_id": "2330", "country": "Taiwan",
        "revenue": [100.0 + i for i in range(15)], "revenue_month": [p.month for p in periods],
        "revenue_year": [p.year for p in periods], "create_time": "",
    })


def make_financials():
    return pd.DataFrame([
        {"date": pd.Timestamp(q), "stock_id": "2330", "type": "EPS", "value": 1.0, "origin_name": ""}
        for q in ("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30")
    ])


def make_valuation():
    return pd.DataFrame({
        "date": PRICE_DAYS[-80:-1], "stock_id": "2330",
        "pe_ratio": 20.0, "pb_ratio": 5.0, "dividend_yield": 2.0,
    })


def make_news():
    return pd.DataFrame([
        {"date": pd.Timestamp("2026-09-29"), "stock_id": "2330", "title": "舊聞", "link": "https://a", "source": "cnyes"},
        {"date": pd.Timestamp("2026-10-01"), "stock_id": "2330", "title": "新聞", "link": "https://b", "source": "cnyes"},
        {"date": pd.Timestamp("2026-09-30"), "stock_id": "2330", "title": "新聞", "link": "https://c", "source": "udn"},
        {"date": pd.Timestamp("2026-09-30"), "stock_id": "2330", "title": "中間", "link": "https://d", "source": "udn"},
    ])


def make_stock_info():
    return pd.DataFrame([
        {"stock_id": "2330", "stock_name": "台積電", "industry_category": "半導體業", "market": "twse",
         "date": pd.Timestamp("2026-10-01")},
        {"stock_id": "0056", "stock_name": "元大高股息", "industry_category": "ETF", "market": "twse",
         "date": pd.Timestamp("2026-10-01")},
    ])


def make_data(**overrides) -> StockRawData:
    data = {
        "stock_info": make_stock_info(),
        "prices": make_prices(),
        "dividends": empty(fc._DIVIDEND_RESULT_COLUMNS),
        "splits": empty(fc._SPLIT_PRICE_COLUMNS),
        "institutional": make_institutional(),
        "margin": make_margin(),
        "revenue": make_revenue(),
        "financials": make_financials(),
        "valuation": make_valuation(),
        "news": make_news(),
    }
    data.update(overrides)
    return StockRawData(**data)


# ---------------------------------------------------------------------------


def test_full_data_produces_all_sections():
    result = build_stock_signals("2330", make_data())

    assert result.stock_id == "2330"
    assert result.technical is not None
    assert result.chip is not None
    assert result.fundamental is not None
    assert result.unavailable == {}


def test_data_freshness_per_source():
    freshness = build_stock_signals("2330", make_data()).data_freshness

    assert tuple(freshness) == FRESHNESS_KEYS
    assert freshness["price"] == date(2026, 10, 1)
    assert freshness["institutional"] == CHIP_DAYS[-1].date()
    assert freshness["margin"] == CHIP_DAYS[-1].date()
    assert freshness["revenue"] == date(2026, 8, 1)
    assert freshness["financials"] == date(2026, 6, 30)
    assert freshness["valuation"] == PRICE_DAYS[-2].date()
    assert freshness["news"] == date(2026, 10, 1)


def test_technical_uses_adjusted_prices():
    # 最後一天前做 1:10 面額變更；若沒還原，技術面會出現跌破季線等假訊號
    prices = make_prices()
    split_day = PRICE_DAYS[-1]
    prices.loc[prices["date"] == split_day, ["open", "high", "low", "close"]] /= 10
    splits = pd.DataFrame([{
        "date": split_day, "stock_id": "2330", "type": "面額變更",
        "before_price": float(prices["close"].iloc[-2]),
        "after_price": float(prices["close"].iloc[-2]) / 10,
    }])

    result = build_stock_signals("2330", make_data(prices=prices, splits=splits))

    assert abs(result.technical.snapshot["change_pct"]) < 10


def test_no_prices():
    result = build_stock_signals("2330", make_data(prices=empty(fc._PRICE_COLUMNS)))

    assert result.technical is None
    assert result.unavailable["technical"] == "無股價資料"
    assert result.data_freshness["price"] is None


def test_insufficient_prices_reason_includes_counts():
    required = TECHNICAL.required_price_rows()
    result = build_stock_signals("2330", make_data(prices=make_prices(PRICE_DAYS[-30:])))

    assert result.technical is None
    assert result.unavailable["technical"] == f"股價資料不足（30 筆，需 {required} 筆）"
    assert result.data_freshness["price"] == date(2026, 10, 1)


def test_no_chip_data():
    result = build_stock_signals("2330", make_data(
        institutional=empty(fc._INSTITUTIONAL_INVESTORS_COLUMNS),
        margin=empty(fc._MARGIN_TRADING_COLUMNS),
    ))

    assert result.chip is None
    assert result.unavailable["chip"] == "無三大法人與融資融券資料"
    assert result.data_freshness["institutional"] is None


def test_etf_without_fundamentals():
    result = build_stock_signals("0056", make_data(
        revenue=empty(fc._MONTH_REVENUE_COLUMNS),
        financials=empty(fc._FINANCIAL_STATEMENT_COLUMNS),
        valuation=empty(fc._VALUATION_RATIOS_COLUMNS),
    ))

    assert result.fundamental is None
    assert result.unavailable["fundamental"] == "無月營收、財報與估值資料（ETF 等標的屬正常）"
    assert result.data_freshness["revenue"] is None


def test_news_sorted_newest_first_and_deduplicated_by_title():
    news = build_stock_signals("2330", make_data()).news

    assert [(n.title, n.date) for n in news] == [
        ("新聞", date(2026, 10, 1)), ("中間", date(2026, 9, 30)), ("舊聞", date(2026, 9, 29)),
    ]
    assert news[0].link == "https://b"


def test_news_limited_to_max_items():
    result = build_stock_signals("2330", make_data(), SignalParams(news_max_items=2))

    assert len(result.news) == 2


def test_no_news():
    result = build_stock_signals("2330", make_data(news=empty(fc._NEWS_COLUMNS)))

    assert result.news == []
    assert result.data_freshness["news"] is None


def test_json_output_is_valid_with_nan_as_null():
    # 成交量全為 0 → 量能比為 NaN，輸出 JSON 時要變成 null 而不是非法的 NaN
    prices = make_prices().assign(volume=0)

    payload = build_stock_signals("2330", make_data(prices=prices)).model_dump_json()

    def reject(constant):  # Python 的 json.loads 預設接受非標準的 NaN/Infinity，這裡改為拒絕
        raise ValueError(f"非法 JSON 常數：{constant}")

    parsed = json.loads(payload, parse_constant=reject)
    assert parsed["technical"]["snapshot"]["volume_ratio"] is None


def test_custom_news_filter_is_used():
    """之後改用 LLM 過濾時，傳入同介面的實作即可。"""
    def only_first(news):
        return news.sort_values("date", ascending=False).head(1)

    result = build_stock_signals("2330", make_data(), news_filter=only_first)

    assert [n.title for n in result.news] == ["新聞"]


def test_default_filter_excludes_forum_posts():
    news = pd.concat([make_news(), pd.DataFrame([{
        "date": pd.Timestamp("2026-10-01"), "stock_id": "2330",
        "title": "2330 台積電 - 閒聊- 股市爆料同學會 - CMoney", "link": "https://e", "source": "CMoney",
    }])])

    result = build_stock_signals("2330", make_data(news=news))

    assert all("股市爆料同學會" not in n.title for n in result.news)


def test_profile_and_price_levels_included():
    result = build_stock_signals("2330", make_data())

    assert result.profile.stock_name == "台積電"
    assert result.price_levels is not None
    assert result.price_levels.kind == "stock"
    assert result.price_levels.close == result.technical.snapshot["close"]


def test_price_levels_use_profile_kind_for_ticks():
    result = build_stock_signals("0056", make_data(prices=make_prices().assign(stock_id="0056")))

    assert result.price_levels.kind == "fund"


def test_unknown_profile_reported_and_levels_not_tick_aligned():
    result = build_stock_signals("2330", make_data(stock_info=empty(fc._STOCK_INFO_COLUMNS)))

    assert result.profile is None
    assert result.unavailable["profile"] == "查無股票基本資料"
    assert result.price_levels.kind == "other"


def test_no_price_levels_when_prices_insufficient():
    result = build_stock_signals("2330", make_data(prices=make_prices(PRICE_DAYS[-30:])))

    assert result.price_levels is None
    assert result.unavailable["price_levels"] == result.unavailable["technical"]
