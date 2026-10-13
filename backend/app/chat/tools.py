"""聊天工具註冊表與權限分級。

規格（Stage 8 spec，2026-10-13 使用者確認三級權限）
================================================

權限等級
--------
- ``auto``（一般）：LLM 呼叫即執行
- ``confirm``（危險）：LLM 呼叫時**不執行**，由 chat_service 建立待確認動作，只有人按確認按鈕
  （``chat/actions.py``）才執行。單向門或會花錢的動作屬於此級
- 禁止：**不註冊成工具**（LLM 無法呼叫），只列在 ``FORBIDDEN_ACTIONS``，由 system prompt 告知 LLM
  「這件事請使用者到哪裡做」
分級寫死在程式（有測試保護），不開放設定檔修改，避免改錯設定讓危險動作自動執行。

工具（``TOOLS``，名稱 → ``Tool``）
-----------------------------------
| 名稱 | 等級 | 參數 | 回傳 data |
|---|---|---|---|
| list_watchlist | auto | — | {count, items: [{stock_id, stock_name}]} |
| add_watchlist_stock | auto | stock_id | {added: {stock_id, stock_name}} |
| remove_watchlist_stock | confirm | stock_id | {removed: {stock_id, stock_name}} |
| get_latest_price | auto | stock_id | PriceQuote（含「非即時、YYYY-MM-DD 收盤」說明） |
| get_stock_report | auto | stock_id, analysis_date? | 報告（見下） |
| get_report_history | auto | stock_id, start?, end? | {stock_id, items: [每日最新一份的重點]}，最多 30 筆 |
| analyze_stock | confirm | stock_id | 報告（見下） |

- 參數用 pydantic model 驗證（多餘欄位拒絕）；stock_id 一律經 ``crud.normalize_stock_id``
- 報告 data：stock_id、stock_name、analysis_date、generated_at、llm_status、report（StockReport JSON 或 None）、
  report_error、warnings、facts（``build_facts`` 的事實清單，供回答「為什麼」類問題；不含新聞連結）
- 查無資料 → 丟例外（``ReportNotFoundError`` / ``QuoteNotFoundError`` / ``WatchlistNotFoundError`` …），
  由 chat_service 轉成 ``{"ok": false, "error"}`` 回給 LLM
- confirm 級工具另有：
  - ``describe(ctx, args) -> str``：確認按鈕上的說明（例：「移除追蹤：2330 台積電」）；同時做前置檢查，
    不可能成功時直接丟例外、不建立待確認動作（例：要移除的股票不在清單、要分析的代號查無）
  - ``format_result(data) -> str``：按下確認後顯示的固定格式訊息（A 方案，不再呼叫 LLM 轉述）

``openai_tool_schemas() -> list[dict]``：給 Chat Completions ``tools`` 參數；confirm 級工具的描述
標明「需使用者按確認才會執行」。

``ToolContext``：session、stock_lookup、quote_provider、run_analysis（分析＋存檔，共用分析鎖，回傳 AnalysisReport 列）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.app.chat.quote import QuoteProvider
from backend.app.data_sources.stock_profile import StockProfile
from backend.app.db import crud
from backend.app.db.crud import ReportNotFoundError, WatchlistNotFoundError
from backend.app.db.models import AnalysisReport
from backend.app.llm.report_generator import build_facts
from backend.app.pipeline.analyze_stock import StockNotFoundError
from backend.app.pipeline.watchlist import add_stock_to_watchlist

ToolLevel = Literal["auto", "confirm"]
HISTORY_LIMIT = 30
CONFIRM_NOTE = "【危險動作：呼叫後不會立即執行，需使用者在畫面上按確認才會執行】"


class QuoteNotFoundError(Exception):
    """近期查無成交資料。"""


@dataclass
class ToolContext:
    session: Session
    stock_lookup: Callable[[str], StockProfile | None]
    quote_provider: QuoteProvider
    run_analysis: Callable[[str], AnalysisReport]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    level: ToolLevel
    args_model: type[BaseModel]
    handler: Callable[[ToolContext, Any], dict]
    describe: Callable[[ToolContext, Any], str] | None = None
    format_result: Callable[[dict], str] | None = None


@dataclass(frozen=True)
class ForbiddenAction:
    name: str
    guidance: str


# ---------------------------------------------------------------------------
# 參數
# ---------------------------------------------------------------------------

class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StockArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_id: str = Field(description="台股代號，例如 2330、0056、00981A")


class ReportArgs(StockArgs):
    analysis_date: date | None = Field(default=None, description="指定分析日期（YYYY-MM-DD）；不給則取最新一份")


class HistoryArgs(StockArgs):
    start: date | None = Field(default=None, description="起日（YYYY-MM-DD，含）")
    end: date | None = Field(default=None, description="迄日（YYYY-MM-DD，含）")


# ---------------------------------------------------------------------------
# 共用
# ---------------------------------------------------------------------------

BIAS = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}
CONFIDENCE = {"low": "低", "medium": "中", "high": "高"}
HOLDING = {
    "short_term": "短線（數日至 2 週）", "swing": "波段（數週至 3 個月）",
    "long_term": "長期（3 個月以上）", "not_recommended": "不建議持有",
}


def _label(stock_id: str, stock_name: str | None) -> str:
    return f"{stock_id} {stock_name}" if stock_name else stock_id


def _item(row) -> dict:
    return {"stock_id": row.stock_id, "stock_name": row.stock_name}


def format_price(price: float) -> str:
    return f"{price:f}".rstrip("0").rstrip(".")


def _report_data(row: AnalysisReport) -> dict:
    signals = crud.to_stock_signals(row)
    return {
        "stock_id": row.stock_id,
        "stock_name": signals.profile.stock_name if signals.profile else None,
        "analysis_date": row.analysis_date.isoformat(),
        "generated_at": row.generated_at.isoformat(timespec="seconds"),
        "llm_status": row.llm_status,
        "report": row.report_json,
        "report_error": row.error,
        "warnings": list(row.warnings or []),
        "facts": json.loads(build_facts(signals)),
    }


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------

def _list_watchlist(ctx: ToolContext, args: NoArgs) -> dict:
    items = [_item(row) for row in crud.get_active_watchlist(ctx.session)]
    return {"count": len(items), "items": items}


def _add_watchlist(ctx: ToolContext, args: StockArgs) -> dict:
    return {"added": _item(add_stock_to_watchlist(ctx.session, args.stock_id, ctx.stock_lookup))}


def _describe_remove(ctx: ToolContext, args: StockArgs) -> str:
    stock_id = crud.normalize_stock_id(args.stock_id)
    row = crud.get_watchlist_item(ctx.session, stock_id)
    if row is None:
        raise WatchlistNotFoundError(f"{stock_id} 不在追蹤清單中")
    return f"移除追蹤：{_label(stock_id, row.stock_name)}"


def _remove_watchlist(ctx: ToolContext, args: StockArgs) -> dict:
    return {"removed": _item(crud.remove_watchlist(ctx.session, args.stock_id))}


def _format_remove(data: dict) -> str:
    removed = data["removed"]
    return f"已移除追蹤：{_label(removed['stock_id'], removed['stock_name'])}"


def _latest_price(ctx: ToolContext, args: StockArgs) -> dict:
    stock_id = crud.normalize_stock_id(args.stock_id)
    quote = ctx.quote_provider.get_latest_quote(stock_id)
    if quote is None:
        raise QuoteNotFoundError(f"近期查無 {stock_id} 的成交資料（可能代號錯誤、停止交易或尚未上市）")
    return quote.model_dump(mode="json")


def _stock_report(ctx: ToolContext, args: ReportArgs) -> dict:
    stock_id = crud.normalize_stock_id(args.stock_id)
    row = crud.get_latest_report(ctx.session, stock_id, args.analysis_date)
    if row is None:
        when = f"（{args.analysis_date.isoformat()}）" if args.analysis_date else ""
        raise ReportNotFoundError(f"{stock_id} 尚無分析報告{when}")
    return _report_data(row)


def _report_history(ctx: ToolContext, args: HistoryArgs) -> dict:
    stock_id = crud.normalize_stock_id(args.stock_id)
    rows = crud.get_report_history(ctx.session, stock_id, start=args.start, end=args.end)[:HISTORY_LIMIT]
    items = []
    for row in rows:
        report = row.report_json or {}
        items.append({
            "analysis_date": row.analysis_date.isoformat(),
            "generated_at": row.generated_at.isoformat(timespec="seconds"),
            "llm_status": row.llm_status,
            "overall_bias": report.get("overall_bias"),
            "summary": report.get("summary"),
            "confidence": report.get("confidence"),
            "target_price": (report.get("target_price") or {}).get("price"),
            "stop_loss": (report.get("stop_loss") or {}).get("price"),
        })
    return {"stock_id": stock_id, "items": items}


def _describe_analyze(ctx: ToolContext, args: StockArgs) -> str:
    stock_id = crud.normalize_stock_id(args.stock_id)
    profile = ctx.stock_lookup(stock_id)
    if profile is None:
        raise StockNotFoundError(f"查無股票代號 {stock_id}")
    return f"分析 {_label(stock_id, profile.stock_name)}（會呼叫 OpenAI，產生少量費用）"


def _analyze(ctx: ToolContext, args: StockArgs) -> dict:
    return _report_data(ctx.run_analysis(crud.normalize_stock_id(args.stock_id)))


def _points(points: list[dict]) -> str:
    return "；".join(f"{format_price(p['price'])}（{p['basis']}，{p['condition']}）" for p in points)


def _point(point: dict | None) -> str:
    return "無" if point is None else _points([point])


def _format_analysis(data: dict) -> str:
    lines = [f"已完成分析：{_label(data['stock_id'], data['stock_name'])}（資料日期 {data['analysis_date']}）"]
    report = data["report"]
    if report is None:
        lines.append(f"報告未產生（{data['llm_status']}）：{data['report_error']}。"
                     "技術、籌碼、基本面訊號已儲存，可到儀表板查看。")
        return "\n".join(lines)
    lines += [
        f"看法：{BIAS[report['overall_bias']]}｜信心：{CONFIDENCE[report['confidence']]}",
        f"摘要：{report['summary']}",
        f"買點：{_points(report['entry_points']) or '無（目前不建議進場）'}",
        f"賣點：{_points(report['exit_points']) or '無'}",
        f"目標價：{_point(report['target_price'])}",
        f"停損：{_point(report['stop_loss'])}",
        f"持有建議：{HOLDING[report['holding_period']]}",
    ]
    if data["warnings"]:
        lines.append("注意：" + "；".join(data["warnings"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 註冊表
# ---------------------------------------------------------------------------

_TOOL_LIST = (
    Tool("list_watchlist", "列出目前的追蹤清單。", "auto", NoArgs, _list_watchlist),
    Tool("add_watchlist_stock", "把股票加入追蹤清單（會先確認代號存在）。", "auto", StockArgs, _add_watchlist),
    Tool("remove_watchlist_stock", "把股票從追蹤清單移除。", "confirm", StockArgs, _remove_watchlist,
         describe=_describe_remove, format_result=_format_remove),
    Tool("get_latest_price",
         "查詢股票最近一個交易日的收盤行情（開高低收、漲跌、成交張數）。不是即時價，回覆必須標明資料日期。",
         "auto", StockArgs, _latest_price),
    Tool("get_stock_report",
         "查詢已存在的分析報告（看法、買賣點、目標價、停損、持有建議）與當時的事實資料（技術指標、籌碼、"
         "基本面、價位、新聞）。不會重新分析。", "auto", ReportArgs, _stock_report),
    Tool("get_report_history", f"查詢某檔股票過去的分析報告重點（每天最新一份，最多 {HISTORY_LIMIT} 筆，新到舊）。",
         "auto", HistoryArgs, _report_history),
    Tool("analyze_stock", "對單一股票重新抓資料並產生分析報告（會呼叫 OpenAI，產生費用）。",
         "confirm", StockArgs, _analyze, describe=_describe_analyze, format_result=_format_analysis),
)
TOOLS: dict[str, Tool] = {tool.name: tool for tool in _TOOL_LIST}

FORBIDDEN_ACTIONS: tuple[ForbiddenAction, ...] = (
    ForbiddenAction("analyze_watchlist", "一次分析整份追蹤清單（費用較高）：請使用者到儀表板按「全部分析」按鈕。"),
    ForbiddenAction("trade", "下單、買賣交易：本系統不支援交易，只提供分析參考，請使用者在自己的券商軟體操作。"),
    ForbiddenAction("change_settings", "修改系統設定、API Key、模型或分析門檻：請使用者直接編輯專案根目錄的 .env"
                                       "（分析門檻在 backend/app/signals/config.py）後重新啟動。"),
)


def openai_tool_schemas() -> list[dict]:
    schemas = []
    for tool in TOOLS.values():
        description = tool.description + (CONFIRM_NOTE if tool.level == "confirm" else "")
        schemas.append({"type": "function", "function": {
            "name": tool.name, "description": description, "parameters": tool.args_model.model_json_schema(),
        }})
    return schemas
