"""Stage 2 彙整結果人工驗證腳本（非TDD範圍）。

用途：依 ``signals/config.py`` 的回溯期間抓齊單一股票所有資料，產出交給 LLM 的
完整事實清單（StockSignals JSON），並印出大小供估算 prompt 長度。

使用方式：
    uv run python backend/scripts/verify_signals.py [stock_id] [--json]
    不帶 --json 時印摘要；帶 --json 時印完整 JSON
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.data_sources.finmind_client import create_finmind_client  # noqa: E402
from backend.app.signals.config import LOOKBACK  # noqa: E402
from backend.app.signals.signal_builder import StockRawData, build_stock_signals  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--json"]
    stock_id = args[0] if args else "2330"
    today = date.today()
    end = today.isoformat()

    def start(days: int) -> str:
        return (today - timedelta(days=days)).isoformat()

    client = create_finmind_client()
    price_start = start(LOOKBACK.price)
    data = StockRawData(
        stock_info=client.get_stock_info(),
        prices=client.get_price(stock_id, price_start, end),
        dividends=client.get_dividend_result(stock_id, price_start, end),
        splits=client.get_split_price(price_start, end),
        institutional=client.get_institutional_investors(stock_id, start(LOOKBACK.institutional), end),
        margin=client.get_margin_trading(stock_id, start(LOOKBACK.margin), end),
        revenue=client.get_month_revenue(stock_id, start(LOOKBACK.month_revenue), end),
        financials=client.get_financial_statement(stock_id, start(LOOKBACK.financial_statement), end),
        valuation=client.get_valuation_ratios(stock_id, start(LOOKBACK.valuation), end),
        news=client.get_news(stock_id, start(LOOKBACK.news - 1), end),
    )
    result = build_stock_signals(stock_id, data)
    payload = result.model_dump_json(indent=2)

    if "--json" in sys.argv:
        print(payload)
        return

    name = result.profile.stock_name if result.profile else "（查無名稱）"
    print(f"{stock_id} {name} 資料日期：")
    for key, value in result.data_freshness.items():
        print(f"  {key:14} {value or '—'}")
    for section in ("technical", "chip", "fundamental"):
        part = getattr(result, section)
        if part is None:
            print(f"\n[{section}] 無：{result.unavailable[section]}")
            continue
        print(f"\n[{section}] {len(part.signals)} 個訊號")
        for signal in part.signals:
            print(f"  [{signal.bias:7}] {signal.date} {signal.description}")
    levels = result.price_levels
    if levels is None:
        print(f"\n[price_levels] 無：{result.unavailable['price_levels']}")
    else:
        flags = [k for k, v in levels.flags.items() if v] or "無"
        print(f"\n[price_levels] 現價 {levels.close}（升降單位類別 {levels.kind}），旗標 {flags}")
        for title, items in (("壓力", levels.resistances), ("支撐", levels.supports)):
            for lv in items[:5]:
                zone = f" ～ 看盤軟體 {lv.chart_price}" if lv.chart_price is not None else ""
                when = f"（{lv.date}）" if lv.date else ""
                print(f"  {title} {lv.price}{zone}  {lv.source}{when}  {lv.distance_pct:+.2f}%")
        if levels.fill_gap:
            gap = levels.fill_gap
            status = f"已於 {gap.filled_date} 填息" if gap.filled else "尚未填息"
            print(f"  填息價 {gap.fill_price}（{gap.ex_date} 除權息 {gap.dividend}）{status}")
    print(f"\n[news] {len(result.news)} 則")
    for item in result.news[:5]:
        print(f"  {item.date} {item.title}")
    print(f"\nJSON 大小：{len(payload):,} 字元（完整內容加 --json 查看）")


if __name__ == "__main__":
    main()
