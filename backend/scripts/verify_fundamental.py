"""Stage 2 基本面訊號人工驗證腳本（非TDD範圍）。

用途：抓真實月營收、財報、估值資料，印出基本面數值與觸發的訊號，可以和券商App
或公開資訊觀測站的月營收、EPS、本益比對照。

使用方式：
    uv run python backend/scripts/verify_fundamental.py [stock_id]
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.data_sources.finmind_client import create_finmind_client  # noqa: E402
from backend.app.signals.config import LOOKBACK  # noqa: E402
from backend.app.signals.fundamental_signals import detect_fundamental_signals  # noqa: E402


def main() -> None:
    stock_id = sys.argv[1] if len(sys.argv) > 1 else "2330"
    today = date.today()
    end = today.isoformat()

    def start(days: int) -> str:
        return (today - timedelta(days=days)).isoformat()

    client = create_finmind_client()
    result = detect_fundamental_signals(
        client.get_month_revenue(stock_id, start(LOOKBACK.month_revenue), end),
        client.get_financial_statement(stock_id, start(LOOKBACK.financial_statement), end),
        client.get_valuation_ratios(stock_id, start(LOOKBACK.valuation), end),
    )
    if result is None:
        print(f"{stock_id}：查無基本面資料（ETF 等沒有財報/月營收的標的屬正常）")
        return

    print(f"{stock_id}：營收最新 {result.as_of_revenue}（所屬月份），財報最新 {result.as_of_financials}（季底），"
          f"估值最新 {result.as_of_valuation}")
    print("\n===== 基本面數值 =====")
    for key, value in result.snapshot.items():
        print(f"  {key:24} {'—' if value is None else f'{value:,.2f}'}")
    print("\n===== 訊號 =====")
    for signal in result.signals:
        threshold = f" / 門檻 {signal.threshold:,.2f}" if signal.threshold is not None else ""
        value = f"  值 {signal.value:,.2f}" if signal.value is not None else ""
        print(f"  [{signal.bias:7}] {signal.date}（{signal.days_ago} 期前）{signal.description}{value}{threshold}")
    if not result.signals:
        print("  （無）")


if __name__ == "__main__":
    main()
