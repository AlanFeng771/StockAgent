"""Stage 2 還原股價人工驗證腳本（非TDD範圍）。

用途：抓真實股價與除權息/面額變更資料，比較事件日前後「原始價」與「還原價」的
單日漲跌幅。還原正確的話，事件日的假跳空應該消失（還原價漲跌幅 ≈ 當天真實漲跌），
且最新一筆還原價等於原始價。

使用方式：
    uv run python backend/scripts/verify_price_adjust.py [stock_id] [start_date] [end_date]
    例：0056（高股息，季配息）、6763（2024-09-09 面額變更 491→49.1）
        uv run python backend/scripts/verify_price_adjust.py 6763 2024-08-01 2024-09-30
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.data_sources.finmind_client import create_finmind_client  # noqa: E402
from backend.app.indicators.price_adjust import adjust_prices  # noqa: E402


def main() -> None:
    stock_id = sys.argv[1] if len(sys.argv) > 1 else "0056"
    end = sys.argv[3] if len(sys.argv) > 3 else date.today().isoformat()
    start = sys.argv[2] if len(sys.argv) > 2 else (date.fromisoformat(end) - timedelta(days=365)).isoformat()

    client = create_finmind_client()
    prices = client.get_price(stock_id, start, end)
    dividends = client.get_dividend_result(stock_id, start, end)
    splits = client.get_split_price(start, end)
    df = adjust_prices(prices, dividends, splits)

    if df.empty:
        print("查無股價資料")
        return

    df["raw_change_%"] = df["close"].pct_change() * 100
    df["adj_change_%"] = df["adj_close"].pct_change() * 100

    events = sorted(
        set(dividends["date"]) | set(splits.loc[splits["stock_id"] == stock_id, "date"])
    )
    print(f"{stock_id} {start} ~ {end}，共 {len(df)} 筆股價，事件 {len(events)} 個")
    columns = ["date", "close", "adj_close", "raw_change_%", "adj_change_%", "volume", "adj_volume"]
    for event_date in events:
        after = df.index[df["date"] >= event_date]
        if len(after) == 0:
            continue
        position = after[0]  # 事件日（或停牌後恢復交易的第一天）
        print(f"\n===== 事件日 {event_date.date()}（前兩筆～後一筆）=====")
        print(df.loc[max(position - 2, 0): position + 1, columns].round(2).to_string(index=False))

    last = df.iloc[-1]
    print(f"\n最新一筆 {last['date'].date()}：原始收盤 {last['close']}，還原收盤 {last['adj_close']}，"
          f"{'一致 ✓' if last['close'] == last['adj_close'] else '不一致 ✗'}")


if __name__ == "__main__":
    main()
