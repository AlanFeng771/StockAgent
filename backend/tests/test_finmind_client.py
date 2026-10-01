from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
import requests

from backend.app.data_sources import finmind_client as finmind_client_module
from backend.app.data_sources.finmind_client import (
    FinMindAPIError,
    FinMindAuthError,
    FinMindClient,
    FinMindQuotaExceededError,
    FinMindSponsorRequiredError,
)

SPONSOR_MESSAGE = (
    "FinMind API unexpected response: Your level is free. Please update your user level. "
    "Detail information:https://finmindtrade.com/analysis/#/Sponsor/sponsor"
)


def make_client(**loader_methods) -> FinMindClient:
    """用 SimpleNamespace 當假的 DataLoader，只掛上測試需要的 method。"""
    loader = SimpleNamespace(**loader_methods)
    return FinMindClient(loader=loader)


# ---------------------------------------------------------------------------
# 建構子 / login
# ---------------------------------------------------------------------------

def patch_data_loader(monkeypatch, login_behavior):
    """把模組內的 DataLoader 換成假類別，login_by_token 行為由 login_behavior 決定。"""
    calls = []

    class FakeDataLoader:
        def login_by_token(self, api_token):
            calls.append(api_token)
            login_behavior()

    monkeypatch.setattr(finmind_client_module, "DataLoader", FakeDataLoader)
    return calls


def test_constructor_logs_in_with_token(monkeypatch):
    calls = patch_data_loader(monkeypatch, lambda: True)

    FinMindClient(api_token="my-token")

    assert calls == ["my-token"]


def test_constructor_without_token_does_not_log_in(monkeypatch):
    calls = patch_data_loader(monkeypatch, lambda: True)

    FinMindClient()

    assert calls == []


@pytest.mark.parametrize(
    "error, expected_exception",
    [
        # SDK login_by_token 失敗時是 raise Exception(str(resp))，訊息形如 "<Response [401]>"
        (Exception("<Response [401]>"), FinMindAuthError),
        (Exception("<Response [403]>"), FinMindAuthError),
        (Exception("<Response [500]>"), FinMindAPIError),
        (requests.ConnectionError("network down"), FinMindAPIError),
    ],
)
def test_constructor_classifies_login_errors(monkeypatch, error, expected_exception):
    def fail():
        raise error

    patch_data_loader(monkeypatch, fail)

    with pytest.raises(expected_exception):
        FinMindClient(api_token="bad-token")


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
        # 只能依狀態碼分類，回應內文裡出現的數字（股票代號、日期）不可誤判
        ("Final response status: 500, text: stock_id 2402 failed", FinMindAPIError),
        ("Final response status: 500, text: 4010 not found", FinMindAPIError),
        (SPONSOR_MESSAGE, FinMindSponsorRequiredError),
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


# ---------------------------------------------------------------------------
# get_dividend_result（除權息結果，供自行計算還原股價）
# ---------------------------------------------------------------------------

def test_get_dividend_result_normal_response_renames_columns():
    # 欄位與數值取自真實API（2330 於 2026-09-16 除息7元）
    raw = pd.DataFrame([{
        "date": "2026-09-16", "stock_id": "2330",
        "before_price": 2385.0, "after_price": 2377.99,
        "stock_and_cache_dividend": 7.000001, "stock_or_cache_dividend": "息",
        "max_price": 2615.0, "min_price": 2145.0, "open_price": 2380.0,
        "reference_price": 2377.99,
    }])
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return raw

    client = make_client(taiwan_stock_dividend_result=fake)

    df = client.get_dividend_result("2330", "2026-01-01", "2026-09-30")

    assert calls == [{"stock_id": "2330", "start_date": "2026-01-01", "end_date": "2026-09-30"}]
    assert list(df.columns) == [
        "date", "stock_id", "before_price", "reference_price", "dividend", "dividend_type",
    ]
    row = df.iloc[0]
    assert row["before_price"] == 2385.0
    assert row["reference_price"] == 2377.99
    assert row["dividend"] == 7.000001
    assert row["dividend_type"] == "息"
    assert pd.api.types.is_datetime64_any_dtype(df["date"])


def test_get_dividend_result_empty_response_returns_empty_dataframe_with_expected_columns():
    client = make_client(taiwan_stock_dividend_result=lambda **kwargs: pd.DataFrame())

    df = client.get_dividend_result("2330", "2026-01-01", "2026-09-30")

    assert df.empty
    assert list(df.columns) == [
        "date", "stock_id", "before_price", "reference_price", "dividend", "dividend_type",
    ]


# ---------------------------------------------------------------------------
# get_split_price（面額變更/分割，全市場查詢）
# ---------------------------------------------------------------------------

def test_get_split_price_queries_whole_market_and_keeps_expected_columns():
    # 欄位與數值取自真實API（6763 於 2024-09-09 面額變更）
    raw = pd.DataFrame([{
        "date": "2024-09-09", "stock_id": "6763", "type": "面額變更",
        "before_price": 491.0, "after_price": 49.10,
        "max_price": 54.0, "min_price": 44.2, "open_price": 49.1,
    }])
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return raw

    client = make_client(taiwan_stock_split_price=fake)

    df = client.get_split_price("2024-01-01", "2026-09-30")

    assert calls == [{"start_date": "2024-01-01", "end_date": "2026-09-30"}]
    assert list(df.columns) == ["date", "stock_id", "type", "before_price", "after_price"]
    assert df.iloc[0]["after_price"] == 49.10
    assert pd.api.types.is_datetime64_any_dtype(df["date"])


def test_get_split_price_empty_response_returns_empty_dataframe_with_expected_columns():
    client = make_client(taiwan_stock_split_price=lambda **kwargs: pd.DataFrame())

    df = client.get_split_price("2024-01-01", "2026-09-30")

    assert df.empty
    assert list(df.columns) == ["date", "stock_id", "type", "before_price", "after_price"]


# ---------------------------------------------------------------------------
# get_trading_dates（台股交易日曆）
# ---------------------------------------------------------------------------

def test_get_trading_dates_normal_response_returns_sorted_datetime_column():
    # 真實API：2026-10-09（週五，國慶補假）不在交易日清單內
    raw = pd.DataFrame({"date": ["2026-10-12", "2026-10-08", "2026-10-07"]})
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return raw

    client = make_client(taiwan_stock_trading_date=fake)

    df = client.get_trading_dates("2026-10-01", "2026-10-15")

    assert calls == [{"start_date": "2026-10-01", "end_date": "2026-10-15"}]
    assert list(df.columns) == ["date"]
    assert pd.api.types.is_datetime64_any_dtype(df["date"])
    assert list(df["date"].dt.strftime("%Y-%m-%d")) == ["2026-10-07", "2026-10-08", "2026-10-12"]


def test_get_trading_dates_empty_response_returns_empty_dataframe_with_expected_columns():
    """超出FinMind已公布範圍（例如實測10月時查隔年）會回傳空資料，不是錯誤。"""
    client = make_client(taiwan_stock_trading_date=lambda **kwargs: pd.DataFrame())

    df = client.get_trading_dates("2027-01-01", "2027-03-01")

    assert df.empty
    assert list(df.columns) == ["date"]


def test_new_methods_raise_sponsor_required_error():
    def raise_sponsor(**kwargs):
        raise Exception(SPONSOR_MESSAGE)

    client = make_client(taiwan_stock_dividend_result=raise_sponsor)

    with pytest.raises(FinMindSponsorRequiredError):
        client.get_dividend_result("2330", "2026-01-01", "2026-09-30")
