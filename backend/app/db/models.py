"""資料表定義（SQLAlchemy 2.x）。

規格（Stage 5 spec，2026-10-01 使用者確認）
==========================================

- ``Watchlist``：stock_id 唯一；``is_active`` 軟刪除。重新加入已移除的股票時**恢復原紀錄**，
  不新增第二筆
- ``AnalysisReport``：**每次分析都保留一筆**（不做同日覆蓋，因為 prompt 會持續調整，保留才能比較
  新舊版本差異），查詢時預設取最新一份。除報告與訊號外，記錄可追溯欄位：model、prompt_version、
  warnings、initial_warnings、repair_attempts、token 用量
  - ``signals_json``：``StockSignals``（含技術指標快照、價位、新聞）
  - ``report_json``：``StockReport``；LLM 沒有產出時為 NULL
- ``ChatMessage``：聊天紀錄（Stage 8 使用）
時間欄位為本機時間（naive datetime；本專案在台灣本機執行）。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Watchlist(Base):
    __tablename__ = "watchlist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[str] = mapped_column(String(16), unique=True)
    stock_name: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class AnalysisReport(Base):
    __tablename__ = "analysis_report"
    __table_args__ = (Index("ix_report_stock_date_time", "stock_id", "analysis_date", "generated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_id: Mapped[str] = mapped_column(String(16))
    analysis_date: Mapped[date] = mapped_column(Date)
    generated_at: Mapped[datetime] = mapped_column(DateTime)
    llm_status: Mapped[str] = mapped_column(String(16))
    signals_json: Mapped[dict] = mapped_column(JSON)
    report_json: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    initial_warnings: Mapped[list] = mapped_column(JSON, default=list)
    repair_attempts: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = (Index("ix_chat_session_time", "session_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    related_stock_id: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
