"""Stage 2 技術指標人工驗證腳本（非TDD範圍）。

用途：抓真實資料、還原股價後計算技術指標，印出最近幾天的數值，可以和券商
看盤軟體對照。

對照時注意：
- 看盤軟體多半用**原始價**計算；本專案用還原價。近期沒有除權息/面額變更的股票，
  兩者應該一致；有事件的股票會有差異，這是預期行為
- KD、MACD、RSI 是遞迴計算，起算點不同會有些微差距，資料越長差距越小
- 看盤App上標示「MACD」的數值對應這裡的 macd_signal（不是 macd_dif）

使用方式：
    uv run python backend/scripts/verify_technical.py [stock_id]
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.data_sources.finmind_client import create_finmind_client  # noqa: E402
from backend.app.indicators.price_adjust import adjust_prices  # noqa: E402
from backend.app.indicators.technical import compute_technical  # noqa: E402
from backend.app.signals.config import LOOKBACK  # noqa: E402


def main() -> None:
    stock_id = sys.argv[1] if len(sys.argv) > 1 else "2330"
    end = date.today()
    start = (end - timedelta(days=LOOKBACK.price)).isoformat()
    end = end.isoformat()

    client = create_finmind_client()
    prices = client.get_price(stock_id, start, end)
    dividends = client.get_dividend_result(stock_id, start, end)
    splits = client.get_split_price(start, end)
    df = compute_technical(adjust_prices(prices, dividends, splits))

    events = [*dividends["date"], *splits.loc[splits["stock_id"] == stock_id, "date"]]
    event_text = "、".join(d.strftime("%Y-%m-%d") for d in sorted(events)) or "無"
    print(f"{stock_id}：{len(df)} 筆交易日，期間內除權息/面額變更：{event_text}")

    columns = [
        "date", "close", "ma5", "ma20", "ma60", "rsi6", "rsi12", "k", "d",
        "macd_dif", "macd_signal", "macd_hist", "bb_upper", "bb_lower",
    ]
    view = df[columns].tail(5).copy()
    view["date"] = view["date"].dt.strftime("%Y-%m-%d")
    print(view.round(2).to_string(index=False))


if __name__ == "__main__":
    main()
