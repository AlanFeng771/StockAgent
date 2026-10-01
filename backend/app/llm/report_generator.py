"""呼叫 ChatGPT 依事實清單產出分析報告。

規格（Stage 3 spec）
====================

``generate_report(signals, client=None, settings=None, prompt=None) -> ReportResult``

事實清單（``build_facts``）
--------------------------
``StockSignals`` 轉成 JSON 送給 LLM，但**去掉新聞連結**（實測 2330 新聞連結佔新聞一半以上篇幅，
LLM 也無法開啟；連結仍保留在 StockSignals 供網頁顯示），以不縮排的緊湊格式輸出。

呼叫
----
- ``client.chat.completions.parse(model, messages, response_format=StockReport, temperature, timeout)``
  （openai SDK 3.22.1 實測可用）；messages = system prompt + 填入事實的 user prompt
- ``client`` 為 None 時依 ``settings.openai_api_key`` 建立；測試注入假 client

``ReportResult``（不丟例外，讓 pipeline 在 LLM 出錯時仍能完成訊號產出）
-----------------------------------------------------------------------
- ``llm_status``：
  - ``pending``：沒有 API key、或仍是 .env.example 的範例值（不呼叫 API）
  - ``failed``：API 錯誤、逾時、模型拒答（refusal）、輸出無法解析
  - ``success``：取得報告
- ``report``：成功時為 ``StockReport``，其餘 None
- ``error``：失敗/待處理的原因
- ``warnings``：
  - 報告中**不在允許清單內的價格**（允許：price_levels 各價位的 price、chart_price、
    現價 close、填息價 fill_price；比較到小數 2 位）；沒有 price_levels 卻給了價格也列入
  - 價格關係：有買點卻沒停損（且買點下方有支撐可用）、想持有卻沒目標價（且上方有壓力可用）、
    停損價 >= 最低買點、目標價 <= 現價或 <= 最高買點、賣點 <= 現價（跌破出場屬於停損）或 <= 最高買點
- ``model`` / ``prompt_version``：使用的模型與 prompt 版本（可追溯）
- ``prompt_tokens`` / ``completion_tokens``：API 回傳的用量，沒有時為 None
"""

from __future__ import annotations

import json
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel

from backend.app.config import Settings, get_settings
from backend.app.llm.prompt_templates import PromptTemplate, load_prompt
from backend.app.llm.report_schema import StockReport
from backend.app.signals.signal_builder import StockSignals

PLACEHOLDER_API_KEY = "your_openai_api_key_here"


class ReportResult(BaseModel):
    llm_status: Literal["success", "pending", "failed"]
    report: StockReport | None
    error: str | None
    warnings: list[str]
    model: str
    prompt_version: str
    prompt_tokens: int | None
    completion_tokens: int | None


def build_facts(signals: StockSignals) -> str:
    data = signals.model_dump(mode="json")
    for item in data["news"]:
        item.pop("link", None)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def generate_report(
    signals: StockSignals,
    client: Any = None,
    settings: Settings | None = None,
    prompt: PromptTemplate | None = None,
) -> ReportResult:
    settings = settings or get_settings()
    prompt = prompt or load_prompt("stock_report")

    def result(status, report=None, error=None, warnings=(), usage=None) -> ReportResult:
        return ReportResult(
            llm_status=status, report=report, error=error, warnings=list(warnings),
            model=settings.openai_model, prompt_version=prompt.version,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )

    api_key = settings.openai_api_key
    if not api_key or api_key == PLACEHOLDER_API_KEY:
        return result("pending", error="未設定 OPENAI_API_KEY（或仍是 .env.example 的範例值）")

    profile = signals.profile
    stock_label = f"{signals.stock_id} {profile.stock_name}" if profile else signals.stock_id
    as_of = signals.data_freshness.get("price") or "未知"
    messages = [
        {"role": "system", "content": prompt.system},
        {"role": "user", "content": prompt.render_user(
            stock_label=stock_label, as_of=str(as_of), facts=build_facts(signals),
        )},
    ]

    try:
        client = client or OpenAI(api_key=api_key)
        completion = client.chat.completions.parse(
            model=settings.openai_model, messages=messages, response_format=StockReport,
            temperature=settings.openai_temperature, timeout=settings.openai_timeout_seconds,
        )
    except Exception as exc:  # API 錯誤、逾時、輸出被截斷等，一律不中斷 pipeline
        return result("failed", error=f"{type(exc).__name__}: {exc}")

    message = completion.choices[0].message
    usage = getattr(completion, "usage", None)
    if getattr(message, "refusal", None):
        return result("failed", error=f"模型拒絕回答：{message.refusal}", usage=usage)
    if message.parsed is None:
        return result("failed", error="模型輸出無法解析為報告格式", usage=usage)
    return result("success", report=message.parsed, warnings=_price_warnings(message.parsed, signals), usage=usage)


def _price_warnings(report: StockReport, signals: StockSignals) -> list[str]:
    points = [("買點", p) for p in report.entry_points] + [("賣點", p) for p in report.exit_points]
    points += [(label, p) for label, p in (("目標價", report.target_price), ("停損價", report.stop_loss)) if p]
    levels = signals.price_levels
    if levels is None:
        return [f"{label} {p.price} 無法驗證：沒有價位清單" for label, p in points]

    allowed = {round(levels.close, 2)}
    for level in levels.supports + levels.resistances:
        allowed.add(round(level.price, 2))
        if level.chart_price is not None:
            allowed.add(round(level.chart_price, 2))
    if levels.fill_gap:
        allowed.add(round(levels.fill_gap.fill_price, 2))
    warnings = [
        f"{label} {p.price}（{p.basis}）不在提供的價位清單中"
        for label, p in points if round(p.price, 2) not in allowed
    ]
    return warnings + _relationship_warnings(report, levels)


def _relationship_warnings(report: StockReport, levels) -> list[str]:
    """價格之間的關係與「有可用價位卻留空」（實測 gpt-4o 會在有價位時仍給 null）。"""
    warnings = []
    close = levels.close
    entries = [p.price for p in report.entry_points]
    lowest_entry = min(entries) if entries else None

    if entries and report.stop_loss is None and any(lv.price < lowest_entry for lv in levels.supports):
        warnings.append("有買點但未給停損價（買點下方有支撐價位可用）")
    wants_position = bool(entries) or report.holding_period != "not_recommended"
    if wants_position and report.target_price is None and levels.resistances:
        warnings.append("未給目標價（現價上方有壓力價位可用）")

    if report.stop_loss and lowest_entry is not None and report.stop_loss.price >= lowest_entry:
        warnings.append(f"停損價 {report.stop_loss.price} 不低於最低買點 {lowest_entry}")
    if report.target_price:
        if report.target_price.price <= close:
            warnings.append(f"目標價 {report.target_price.price} 不高於現價 {close}")
        elif entries and report.target_price.price <= max(entries):
            warnings.append(f"目標價 {report.target_price.price} 不高於最高買點 {max(entries)}")
    for p in report.exit_points:
        if p.price <= close:
            warnings.append(f"賣點 {p.price}（{p.basis}）不高於現價 {close}；跌破出場應放在停損價")
        elif entries and p.price <= max(entries):
            warnings.append(f"賣點 {p.price}（{p.basis}）不高於最高買點 {max(entries)}")
    return warnings
