"""Stage 1 快取人工驗證腳本（非TDD範圍）。

用途：用統一設定（含快取）建立 client，跑一輪單股完整查詢，印出耗時、實際打
API 的次數與快取檔數量。連跑兩次：第二次應該 0 次 API 呼叫、耗時明顯縮短。

使用方式：
    uv run python backend/scripts/verify_cache.py [stock_id]
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.config import get_settings  # noqa: E402
from backend.app.data_sources.finmind_client import create_finmind_client  # noqa: E402


def main() -> None:
    stock_id = sys.argv[1] if len(sys.argv) > 1 else "2330"
    settings = get_settings()
    client = create_finmind_client(settings)

    # 包一層計數，統計實際打到底層SDK（=FinMind API）的次數
    calls = []
    real_loader = client._loader

    class CountingLoader:
        def __getattr__(self, name):
            fn = getattr(real_loader, name)

            def wrapped(**kwargs):
                calls.append(name)
                return fn(**kwargs)
            return wrapped

    client._loader = CountingLoader()

    today = date.today()
    end = today.isoformat()
    start_short = (today - timedelta(days=30)).isoformat()
    start_long = (today - timedelta(days=730)).isoformat()

    started = time.time()
    client.get_price(stock_id, (today - timedelta(days=180)).isoformat(), end)
    client.get_institutional_investors(stock_id, start_short, end)
    client.get_margin_trading(stock_id, start_short, end)
    client.get_financial_statement(stock_id, start_long, end)
    client.get_month_revenue(stock_id, (today - timedelta(days=430)).isoformat(), end)
    client.get_valuation_ratios(stock_id, start_short, end)
    client.get_dividend_result(stock_id, start_long, end)
    client.get_news(stock_id, (today - timedelta(days=6)).isoformat(), end)
    elapsed = time.time() - started

    files = list(settings.cache_dir.glob("*.pkl"))
    print(f"快取目錄: {settings.cache_dir}")
    print(f"實際API呼叫: {len(calls)} 次")
    print(f"耗時: {elapsed:.2f} 秒")
    print(f"快取檔: {len(files)} 個，共 {sum(f.stat().st_size for f in files) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
