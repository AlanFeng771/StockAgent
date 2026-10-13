"""API 請求 / 回應格式。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from backend.app.chat.chat_service import PendingActionOut

from backend.app.db.models import AnalysisReport
from backend.app.llm.report_schema import StockReport
from backend.app.signals.signal_builder import StockSignals


class WatchlistIn(BaseModel):
    stock_id: str


class WatchlistItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stock_id: str
    stock_name: str | None
    created_at: datetime


class ReportSummary(BaseModel):
    id: int
    stock_id: str
    stock_name: str | None
    analysis_date: date
    generated_at: datetime
    llm_status: str
    report: StockReport | None
    error: str | None
    warnings: list[str]
    repair_attempts: int
    model: str
    prompt_version: str
    prompt_tokens: int | None
    completion_tokens: int | None

    @classmethod
    def from_row(cls, row: AnalysisReport, **extra) -> "ReportSummary":
        profile = (row.signals_json or {}).get("profile") or {}
        return cls(
            id=row.id, stock_id=row.stock_id, stock_name=profile.get("stock_name"),
            analysis_date=row.analysis_date, generated_at=row.generated_at, llm_status=row.llm_status,
            report=None if row.report_json is None else StockReport.model_validate(row.report_json),
            error=row.error, warnings=row.warnings or [], repair_attempts=row.repair_attempts,
            model=row.model, prompt_version=row.prompt_version,
            prompt_tokens=row.prompt_tokens, completion_tokens=row.completion_tokens, **extra,
        )


class ReportDetail(ReportSummary):
    signals: StockSignals

    @classmethod
    def from_row(cls, row: AnalysisReport, **extra) -> "ReportDetail":
        return super().from_row(row, signals=StockSignals.model_validate(row.signals_json), **extra)


class RunRequest(BaseModel):
    """觸發分析的請求內容（目前沒有參數，送 {} 即可）。宣告成 JSON body 是為了讓 /docs（Swagger UI）
    會送出 Content-Type: application/json，否則會被「POST 只收 JSON」的保護擋下。"""


class HealthOut(BaseModel):
    status: str
    database: str


class ChatIn(BaseModel):
    session_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,64}$",
                                   description="對話 id；不給則開新對話（回應會帶回新 id）")
    message: str = Field(min_length=1)


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    content: str
    created_at: datetime


class ChatHistoryOut(BaseModel):
    session_id: str
    messages: list[ChatMessageOut]
    pending_actions: list[PendingActionOut]


class ActionRequest(BaseModel):
    """確認／取消待確認動作的請求內容（送 {} 即可；宣告成 JSON body 的原因同 RunRequest）。"""
