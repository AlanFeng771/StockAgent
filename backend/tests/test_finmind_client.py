from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from backend.app.data_sources.finmind_client import (
    FinMindAPIError,
    FinMindAuthError,
    FinMindClient,
    FinMindQuotaExceededError,
)


def make_client(**loader_methods) -> FinMindClient:
    """用 SimpleNamespace 當假的 DataLoader，只掛上測試需要的 method。"""
    loader = SimpleNamespace(**loader_methods)
    return FinMindClient(loader=loader)


# ---------------------------------------------------------------------------
# get_price
# ---------------------------------------------------------------------------

def test_get_price_normal_response_renames_and_normalizes_columns():
    raw = pd.DataFrame([
        {
            "date": "2026-09-28", "stock_id": "2330",
            "Trading_Volume": 1000, "Trading_money": 500000,
            "open": 100.0, "max": 105.0, "min": 99.0, "close": 104.0,
            "spread": 1.5, "Trading_turnover": 300,
        }
    ])
    client = make_client(taiwan_stock_daily=lambda **kwargs: raw)

    df = client.get_price("2330", "2026-09-01", "2026-09-28")

    assert list(df.columns) == [
        "date", "stock_id", "open", "high", "low", "close",
        "volume", "trading_money", "turnover",
    ]
    row = df.iloc[0]
    assert row["high"] == 105.0
    assert row["low"] == 99.0
    assert row["volume"] == 1000
    assert row["trading_money"] == 500000
    assert row["turnover"] == 300
    assert pd.api.types.is_datetime64_any_dtype(df["date"])


def test_get_price_empty_response_returns_empty_dataframe_with_expected_columns():
    client = make_client(taiwan_stock_daily=lambda **kwargs: pd.DataFrame())

    df = client.get_price("9999999", "2026-09-01", "2026-09-28")

    assert df.empty
    assert list(df.columns) == [
        "date", "stock_id", "open", "high", "low", "close",
        "volume", "trading_money", "turnover",
    ]


@pytest.mark.parametrize(
    "message, expected_exception",
    [
        ("Final response status: 402, text: quota exceeded", FinMindQuotaExceededError),
        ("Final response status: 401, text: invalid token", FinMindAuthError),
        ("Final response status: 403, text: forbidden", FinMindAuthError),
        ("FinMind API unexpected response: something odd", FinMindAPIError),
        ("Final response status: 500, text: server error", FinMindAPIError),
    ],
)
def test_get_price_classifies_sdk_errors(message, expected_exception):
    def raise_error(**kwargs):
        raise Exception(message)

    client = make_client(taiwan_stock_daily=raise_error)

    with pytest.raises(expected_exception):
        client.get_price("2330", "2026-09-01", "2026-09-28")


# ---------------------------------------------------------------------------
# get_institutional_investors
# ---------------------------------------------------------------------------

def test_get_institutional_investors_normal_response_renames_and_adds_net():
    raw = pd.DataFrame([
        {"date": "2026-09-28", "stock_id": "2330", "name": "Foreign_Investor", "buy": 1000, "sell": 400},
    ])
    client = make_client(taiwan_stock_institutional_investors=lambda **kwargs: raw)

    df = client.get_institutional_investors("2330", "2026-09-01", "2026-09-28")

    assert list(df.columns) == ["date", "stock_id", "investor_type", "buy", "sell", "net"]
    assert df.iloc[0]["investor_type"] == "Foreign_Investor"
    assert df.iloc[0]["net"] == 600


def test_get_institutional_investors_empty_response_returns_empty_dataframe_with_expected_columns():
    client = make_client(taiwan_stock_institutional_investors=lambda **kwargs: pd.DataFrame())

    df = client.get_institutional_investors("2330", "2026-09-01", "2026-09-28")

    assert df.empty
    assert list(df.columns) == ["date", "stock_id", "investor_type", "buy", "sell", "net"]


def test_get_institutional_investors_propagates_classified_errors():
    def raise_error(**kwargs):
        raise Exception("Final response status: 402, text: quota exceeded")

    client = make_client(taiwan_stock_institutional_investors=raise_error)

    with pytest.raises(FinMindQuotaExceededError):
        client.get_institutional_investors("2330", "2026-09-01", "2026-09-28")


# ---------------------------------------------------------------------------
# get_margin_trading
# ---------------------------------------------------------------------------

def test_get_margin_trading_normal_response_renames_columns():
    raw = pd.DataFrame([{
        "date": "2026-09-28", "stock_id": "2330",
        "MarginPurchaseBuy": 10, "MarginPurchaseSell": 5,
        "MarginPurchaseTodayBalance": 100, "MarginPurchaseYesterdayBalance": 95,
        "MarginPurchaseCashRepayment": 0, "MarginPurchaseLimit": 10000,
        "ShortSaleBuy": 2, "ShortSaleSell": 3,
        "ShortSaleTodayBalance": 20, "ShortSaleYesterdayBalance": 19,
        "ShortSaleCashRepayment": 0, "ShortSaleLimit": 5000,
        "OffsetLoanAndShort": 0, "Note": "",
    }])
    client = make_client(taiwan_stock_margin_purchase_short_sale=lambda **kwargs: raw)

    df = client.get_margin_trading("2330", "2026-09-01", "2026-09-28")

    assert df.iloc[0]["margin_purchase_buy"] == 10
    assert df.iloc[0]["short_sale_today_balance"] == 20


def test_get_margin_trading_empty_response_returns_empty_dataframe_with_expected_columns():
    client = make_client(taiwan_stock_margin_purchase_short_sale=lambda **kwargs: pd.DataFrame())

    df = client.get_margin_trading("2330", "2026-09-01", "2026-09-28")

    assert df.empty
    assert "margin_purchase_buy" in df.columns
    assert "short_sale_today_balance" in df.columns


# ---------------------------------------------------------------------------
# get_financial_statement / get_month_revenue / get_news / get_valuation_ratios
# ---------------------------------------------------------------------------

def test_get_financial_statement_normal_response_keeps_long_format():
    raw = pd.DataFrame([
        {"date": "2026-09-28", "stock_id": "2330", "type": "EPS", "value": 2.5, "origin_name": "每股盈餘"},
    ])
    client = make_client(taiwan_stock_financial_statement=lambda **kwargs: raw)

    df = client.get_financial_statement("2330", "2026-01-01", "2026-09-28")

    assert list(df.columns) == ["date", "stock_id", "type", "value", "origin_name"]
    assert df.iloc[0]["type"] == "EPS"


def test_get_financial_statement_empty_response_returns_empty_dataframe_with_expected_columns():
    client = make_client(taiwan_stock_financial_statement=lambda **kwargs: pd.DataFrame())

    df = client.get_financial_statement("2330", "2026-01-01", "2026-09-28")

    assert df.empty
    assert list(df.columns) == ["date", "stock_id", "type", "value", "origin_name"]


def test_get_month_revenue_normal_response():
    raw = pd.DataFrame([{
        "date": "2026-09-01", "stock_id": "2330", "country": "Taiwan",
        "revenue": 1000000, "revenue_month": 8, "revenue_year": 2026,
        "create_time": "2026-09-10",
    }])
    client = make_client(taiwan_stock_month_revenue=lambda **kwargs: raw)

    df = client.get_month_revenue("2330", "2026-01-01", "2026-09-28")

    assert df.iloc[0]["revenue"] == 1000000
    assert df.iloc[0]["revenue_month"] == 8


def test_get_month_revenue_empty_response_returns_empty_dataframe_with_expected_columns():
    client = make_client(taiwan_stock_month_revenue=lambda **kwargs: pd.DataFrame())

    df = client.get_month_revenue("2330", "2026-01-01", "2026-09-28")

    assert df.empty
    assert "revenue" in df.columns


def test_get_news_normal_response_calls_per_day_and_merges_sorted():
    """taiwan_stock_news 只接受單日查詢，get_news 需逐日呼叫並合併排序。"""
    calls = []

    def fake_news(**kwargs):
        calls.append(kwargs)
        day = kwargs["start_date"]
        if day == "2026-09-02":
            return pd.DataFrame([{
                "date": "2026-09-02", "stock_id": "2330", "title": "新聞B",
                "link": "https://example.com/b", "source": "cnyes",
            }])
        if day == "2026-09-01":
            return pd.DataFrame([{
                "date": "2026-09-01", "stock_id": "2330", "title": "新聞A",
                "link": "https://example.com/a", "source": "cnyes",
            }])
        return pd.DataFrame()

    client = make_client(taiwan_stock_news=fake_news)

    df = client.get_news("2330", "2026-09-01", "2026-09-02")

    assert len(calls) == 2
    assert all("end_date" not in kwargs for kwargs in calls)
    assert [kwargs["start_date"] for kwargs in calls] == ["2026-09-01", "2026-09-02"]
    assert list(df["title"]) == ["新聞A", "新聞B"]


def test_get_news_single_day_range_calls_loader_once_without_end_date():
    def fake_news(**kwargs):
        assert kwargs == {"stock_id": "2330", "start_date": "2026-09-28"}
        return pd.DataFrame([{
            "date": "2026-09-28", "stock_id": "2330", "title": "台積電法說會",
            "link": "https://example.com", "source": "cnyes",
        }])

    client = make_client(taiwan_stock_news=fake_news)

    df = client.get_news("2330", "2026-09-28", "2026-09-28")

    assert df.iloc[0]["title"] == "台積電法說會"


def test_get_news_omitted_end_date_queries_single_day_only():
    calls = []

    def fake_news(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame([{
            "date": "2026-09-28", "stock_id": "2330", "title": "台積電法說會",
            "link": "https://example.com", "source": "cnyes",
        }])

    client = make_client(taiwan_stock_news=fake_news)

    df = client.get_news("2330", "2026-09-28")

    assert calls == [{"stock_id": "2330", "start_date": "2026-09-28"}]
    assert df.iloc[0]["title"] == "台積電法說會"


def test_get_news_empty_response_returns_empty_dataframe_with_expected_columns():
    client = make_client(taiwan_stock_news=lambda **kwargs: pd.DataFrame())

    df = client.get_news("2330", "2026-09-01", "2026-09-28")

    assert df.empty
    assert list(df.columns) == ["date", "stock_id", "title", "link", "source"]


def test_get_valuation_ratios_normal_response_renames_columns():
    raw = pd.DataFrame([{
        "date": "2026-09-28", "stock_id": "2330",
        "PER": 18.5, "PBR": 5.2, "dividend_yield": 2.1,
    }])
    client = make_client(taiwan_stock_per_pbr=lambda **kwargs: raw)

    df = client.get_valuation_ratios("2330", "2026-09-01", "2026-09-28")

    assert list(df.columns) == ["date", "stock_id", "pe_ratio", "pb_ratio", "dividend_yield"]
    assert df.iloc[0]["pe_ratio"] == 18.5
    assert df.iloc[0]["pb_ratio"] == 5.2


def test_get_valuation_ratios_empty_response_returns_empty_dataframe_with_expected_columns():
    client = make_client(taiwan_stock_per_pbr=lambda **kwargs: pd.DataFrame())

    df = client.get_valuation_ratios("2330", "2026-09-01", "2026-09-28")

    assert df.empty
    assert list(df.columns) == ["date", "stock_id", "pe_ratio", "pb_ratio", "dividend_yield"]
