"""Stage 2 籌碼面訊號人工驗證腳本（非TDD範圍）。

用途：抓真實三大法人、融資融券資料，印出籌碼數值與觸發的訊號，可以和券商App的
法人買賣超、融資融券頁面對照（App 多以「張」為單位）。

使用方式：
    uv run python backend/scripts/verify_chip.py [stock_id]
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.data_sources.finmind_client import create_finmind_client  # noqa: E402
from backend.app.indicators.price_adjust import adjust_prices  # noqa: E402
from backend.app.signals.chip_signals import detect_chip_signals  # noqa: E402
from backend.app.signals.config import LOOKBACK  # noqa: E402


def main() -> None:
    stock_id = sys.argv[1] if len(sys.argv) > 1 else "2330"
    today = date.today()
    end = today.isoformat()
    price_start = (today - timedelta(days=LOOKBACK.price)).isoformat()

    client = create_finmind_client()
    prices = adjust_prices(
        client.get_price(stock_id, price_start, end),
        client.get_dividend_result(stock_id, price_start, end),
        client.get_split_price(price_start, end),
    )
    institutional = client.get_institutional_investors(
        stock_id, (today - timedelta(days=LOOKBACK.institutional)).isoformat(), end)
    margin = client.get_margin_trading(stock_id, (today - timedelta(days=LOOKBACK.margin)).isoformat(), end)

    result = detect_chip_signals(institutional, margin, prices)
    if result is None:
        print("查無籌碼資料")
        return

    print(f"{stock_id}：股價最新 {prices['date'].max().date()}，"
          f"法人最新 {result.as_of_institutional}，融資最新 {result.as_of_margin}")
    print("\n===== 籌碼數值（張 / %）=====")
    for key, value in result.snapshot.items():
        print(f"  {key:32} {'—' if value is None else f'{value:,.2f}'}")
    print("\n===== 訊號 =====")
    for signal in result.signals:
        threshold = f" / 門檻 {signal.threshold:.2f}" if signal.threshold is not None else ""
        print(f"  [{signal.bias:7}] {signal.date}（{signal.days_ago} 天前）{signal.description}"
              f"  值 {signal.value:.2f}{threshold}")
    if not result.signals:
        print("  （無）")


if __name__ == "__main__":
    main()
