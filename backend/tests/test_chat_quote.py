from __future__ import annotations

from datetime import date

import pandas as pd

from backend.app.chat.quote import FinMindQuoteProvider


class FakePriceClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_price(self, stock_id, start_date, end_date):
        self.calls.append((stock_id, start_date, end_date))
        return pd.DataFrame(self.rows, columns=["date", "stock_id", "open", "high", "low", "close", "volume"])


def row(day, close, volume=12_345_678):
    return {"date": pd.Timestamp(day), "stock_id": "2330", "open": close - 5, "high": close + 5,
            "low": close - 10, "close": close, "volume": volume}


def provider(rows):
    client = FakePriceClient(rows)
    return FinMindQuoteProvider(client=client, today=lambda: date(2026, 10, 13)), client


def test_latest_row_with_change_and_date_note():
    quote_provider, client = provider([row("2026-10-08", 1000.0), row("2026-10-09", 1015.0)])

    quote = quote_provider.get_latest_quote("2330")

    assert client.calls == [("2330", "2026-09-29", "2026-10-13")]
    assert quote.date == date(2026, 10, 9)
    assert quote.close == 1015.0 and quote.prev_close == 1000.0
    assert quote.change == 15.0 and quote.change_pct == 1.5
    assert quote.volume_lots == 12_345
    assert "非即時" in quote.note and "2026-10-09" in quote.note


def test_single_row_has_no_change():
    quote = provider([row("2026-10-09", 1015.0)])[0].get_latest_quote("2330")

    assert quote.prev_close is None and quote.change is None and quote.change_pct is None


def test_no_data_returns_none():
    assert provider([])[0].get_latest_quote("2330") is None


def test_rows_sorted_by_date():
    quote = provider([row("2026-10-09", 1015.0), row("2026-10-08", 1000.0)])[0].get_latest_quote("2330")

    assert quote.date == date(2026, 10, 9) and quote.change == 15.0


def test_change_pct_rounded():
    quote = provider([row("2026-10-08", 30.0), row("2026-10-09", 30.1)])[0].get_latest_quote("2330")

    assert quote.change == 0.1 and quote.change_pct == 0.33
