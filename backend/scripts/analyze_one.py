"""單股端到端人工驗證腳本（Stage 3 / 4，非TDD範圍）。

透過 pipeline.analyze_stock：抓資料 → 規則訊號 → ChatGPT 產出報告，印出報告、價格驗證警告、token 用量。

使用方式：
    uv run python backend/scripts/analyze_one.py 2330            # 實際呼叫 OpenAI（會產生費用）
    uv run python backend/scripts/analyze_one.py 2330 --dry-run  # 只印出要送給 LLM 的 prompt，不呼叫 API
    uv run python backend/scripts/analyze_one.py 2330 --save     # 分析後存入資料庫（每次分析都保留一筆）
"""

from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.app.data_sources.finmind_client import create_finmind_client  # noqa: E402
from backend.app.db.crud import save_report  # noqa: E402
from backend.app.db.database import get_session_factory  # noqa: E402
from backend.app.llm.prompt_templates import load_prompt  # noqa: E402
from backend.app.llm.report_generator import build_facts  # noqa: E402
from backend.app.pipeline.analyze_stock import AnalysisError, DataSourceError, analyze_stock  # noqa: E402
from backend.app.pipeline.fetch import fetch_stock_raw_data  # noqa: E402
from backend.app.signals.signal_builder import build_stock_signals  # noqa: E402

HOLDING = {"short_term": "短線（數日至2週）", "swing": "波段（數週至3個月）",
           "long_term": "中長期（3個月以上）", "not_recommended": "不建議持有"}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    stock_id = args[0] if args else "2330"

    if "--dry-run" in sys.argv:
        signals = build_stock_signals(stock_id, fetch_stock_raw_data(create_finmind_client(), stock_id, date.today()))
        prompt = load_prompt("stock_report")
        facts = build_facts(signals)
        print(f"===== prompt 版本 {prompt.version} =====")
        print(f"system：{len(prompt.system):,} 字元，事實清單：{len(facts):,} 字元")
        print("\n===== 事實清單 =====")
        print(facts)
        return

    try:
        analysis = analyze_stock(stock_id)
    except DataSourceError as exc:
        print(f"資料來源錯誤（{type(exc.source_error).__name__}）：{exc}")
        return
    except AnalysisError as exc:
        print(f"無法分析（{type(exc).__name__}）：{exc}")
        return

    result = analysis.report
    if "--save" in sys.argv:
        with get_session_factory()() as session:
            row = save_report(session, analysis)
        print(f"已存入資料庫（analysis_report id={row.id}）")
    print(f"{stock_id} 分析日期 {analysis.analysis_date}（股價最新一筆）")
    print(f"狀態：{result.llm_status}｜模型 {result.model}｜prompt 版本 {result.prompt_version}"
          f"｜tokens 輸入 {result.prompt_tokens} / 輸出 {result.completion_tokens}")
    if result.report is None:
        print(f"原因：{result.error}")
        return

    r = result.report
    print(f"\n【總結】{r.summary}（整體 {r.overall_bias}，信心 {r.confidence}：{r.confidence_reason}）")

    def show(title, points):
        print(f"\n【{title}】")
        if not points:
            print("  （無）")
        for p in points:
            print(f"  {p.price}｜{p.basis}｜{p.condition}")

    show("買點", r.entry_points)
    show("賣點", r.exit_points)
    show("目標價", [r.target_price] if r.target_price else [])
    print(f"  理由：{r.target_price_reason}")
    show("停損價", [r.stop_loss] if r.stop_loss else [])
    print(f"  理由：{r.stop_loss_reason}")
    print(f"\n【建議持有】{HOLDING[r.holding_period]}：{r.holding_period_reason}")
    print(f"【適合長期投資】{'是' if r.long_term_suitable else '否'}：{r.long_term_reason}")
    print("\n【風險】")
    for risk in r.risks:
        print(f"  - {risk}")
    print("\n【判斷依據】")
    for j in r.rationale:
        print(f"  [{j.aspect}/{j.bias}] {j.point}")
    print("\n【資料限制】")
    for item in r.data_limitations or ["（無）"]:
        print(f"  - {item}")
    if result.repair_attempts:
        print(f"\n（已自動修正 {result.repair_attempts} 次；修正前的警告：）")
        for warning in result.initial_warnings:
            print(f"  - {warning}")
    if result.warnings:
        print("\n⚠ 價格驗證警告：")
        for warning in result.warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    main()
