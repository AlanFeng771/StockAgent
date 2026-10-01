"""API 請求 / 回應格式。"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

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


class HealthOut(BaseModel):
    status: str
    database: str
