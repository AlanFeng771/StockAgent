from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from backend.app.data_sources.finmind_client import FinMindQuotaExceededError
from backend.app.pipeline.fetch import fetch_stock_raw_data
from backend.app.signals.config import LookbackDays


class RecordingClient:
    def __init__(self, fail_on=None):
        self.calls = {}
        self._fail_on = fail_on

    def __getattr__(self, name):
        def method(*args):
            self.calls[name] = args
            if name == self._fail_on:
                raise FinMindQuotaExceededError("402")
            return pd.DataFrame()
        return method


def test_date_ranges_follow_lookback():
    client = RecordingClient()
    lookback = LookbackDays(price=180, institutional=60, margin=60, month_revenue=1130,
                            financial_statement=900, valuation=365, news=7)

    fetch_stock_raw_data(client, "2330", date(2026, 10, 1), lookback)

    assert client.calls["get_price"] == ("2330", "2026-04-04", "2026-10-01")
    assert client.calls["get_dividend_result"] == ("2330", "2026-04-04", "2026-10-01")
    assert client.calls["get_split_price"] == ("2026-04-04", "2026-10-01")
    assert client.calls["get_institutional_investors"] == ("2330", "2026-08-02", "2026-10-01")
    assert client.calls["get_month_revenue"][1] == "2023-08-28"
    assert client.calls["get_news"] == ("2330", "2026-09-25", "2026-10-01")  # 含今天共 7 天
    assert client.calls["get_stock_info"] == ()


def test_client_errors_propagate():
    with pytest.raises(FinMindQuotaExceededError):
        fetch_stock_raw_data(RecordingClient(fail_on="get_margin_trading"), "2330", date(2026, 10, 1))
