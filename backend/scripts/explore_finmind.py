"""Stage 1 人工驗證腳本（非TDD範圍）。

用途：實際呼叫 FinMind API，人工比對各 dataset 的真實回傳欄位是否與
``backend/app/data_sources/finmind_client.py`` 模組docstring裡寫的規格一致。
若有落差，回頭修正規格與 ``test_finmind_client.py`` 裡的假資料。

使用方式：
    uv run python backend/scripts/explore_finmind.py [stock_id]

若 .env 裡有 FINMIND_API_TOKEN 會自動帶入登入；沒有的話以公開額度匿名呼叫
（額度較低，但足夠驗證欄位格式）。
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.data_sources.finmind_client import FinMindClient  # noqa: E402


def main() -> None:
    load_dotenv()
    stock_id = sys.argv[1] if len(sys.argv) > 1 else "2330"
    token = os.environ.get("FINMIND_API_TOKEN") or None

    end = date.today()
    start = end - timedelta(days=60)
    start_str, end_str = start.isoformat(), end.isoformat()
    # get_news 底層限制為單日查詢，client內部逐日迭代呼叫API，
    # 用與其他dataset相同的60天範圍會打上百次請求，這裡刻意縮短範圍。
    news_start_str = (end - timedelta(days=3)).isoformat()

    client = FinMindClient(api_token=token)

    checks = [
        ("get_price", client.get_price, start_str, end_str),
        ("get_institutional_investors", client.get_institutional_investors, start_str, end_str),
        ("get_margin_trading", client.get_margin_trading, start_str, end_str),
        ("get_financial_statement", client.get_financial_statement, start_str, end_str),
        ("get_month_revenue", client.get_month_revenue, start_str, end_str),
        ("get_news", client.get_news, news_start_str, end_str),
        ("get_valuation_ratios", client.get_valuation_ratios, start_str, end_str),
    ]

    for name, method, range_start, range_end in checks:
        print(f"\n===== {name}({stock_id}, {range_start}, {range_end}) =====")
        try:
            df = method(stock_id, range_start, range_end)
        except Exception as exc:
            print(f"  ERROR: {type(exc).__name__}: {exc}")
            continue
        print(f"  columns: {list(df.columns)}")
        print(f"  rows: {len(df)}")
        if not df.empty:
            print(df.head(3).to_string())


if __name__ == "__main__":
    main()
