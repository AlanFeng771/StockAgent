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

    client = FinMindClient(api_token=token)

    print(f"\n===== get_news({stock_id}, {end_str}) [單日，省略end_date] =====")
    try:
        df = client.get_news(stock_id, end_str)
        print(f"  columns: {list(df.columns)}")
        print(f"  rows: {len(df)}")
        if not df.empty:
            print(df.head(3).to_string())
    except Exception as exc:
        print(f"  ERROR: {type(exc).__name__}: {exc}")

    checks = [
        ("get_price", client.get_price),
        ("get_institutional_investors", client.get_institutional_investors),
        ("get_margin_trading", client.get_margin_trading),
        ("get_financial_statement", client.get_financial_statement),
        ("get_month_revenue", client.get_month_revenue),
        ("get_valuation_ratios", client.get_valuation_ratios),
    ]

    for name, method in checks:
        print(f"\n===== {name}({stock_id}, {start_str}, {end_str}) =====")
        _show(lambda: method(stock_id, start_str, end_str))

    # 除權息/分割需要較長區間才查得到事件；交易日曆往後查以確認是否含未來日期
    year_start = date(end.year - 1, 1, 1).isoformat()
    print(f"\n===== get_dividend_result({stock_id}, {year_start}, {end_str}) =====")
    _show(lambda: client.get_dividend_result(stock_id, year_start, end_str))

    print(f"\n===== get_split_price({year_start}, {end_str}) [全市場] =====")
    _show(lambda: client.get_split_price(year_start, end_str))

    future_end = (end + timedelta(days=120)).isoformat()
    print(f"\n===== get_trading_dates({end_str}, {future_end}) =====")
    df = _show(lambda: client.get_trading_dates(end_str, future_end))
    if df is not None and not df.empty:
        print(f"  已公布到: {df['date'].max().date()}")


def _show(fetch):
    try:
        df = fetch()
    except Exception as exc:
        print(f"  ERROR: {type(exc).__name__}: {exc}")
        return None
    print(f"  columns: {list(df.columns)}")
    print(f"  dtypes: {dict(df.dtypes.astype(str))}")
    print(f"  rows: {len(df)}")
    if not df.empty:
        print(df.head(3).to_string())
    return df


if __name__ == "__main__":
    main()
