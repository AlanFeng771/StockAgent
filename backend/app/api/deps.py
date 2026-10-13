"""API 共用：資料庫 session、錯誤對應、只接受 JSON 的 POST。"""

from __future__ import annotations

from typing import Iterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from backend.app.chat.actions import ActionExpiredError, ActionNotFoundError, ActionNotPendingError
from backend.app.chat.chat_service import ChatInputError, ChatLLMError, ChatNotConfiguredError
from backend.app.chat.tools import ToolContext
from backend.app.data_sources.finmind_client import FinMindClientError
from backend.app.db import crud
from backend.app.db.crud import (
    InvalidStockIdError,
    ReportNotFoundError,
    WatchlistAlreadyExistsError,
    WatchlistNotFoundError,
)
from backend.app.db.database import get_session_factory
from backend.app.pipeline.analyze_stock import DataSourceError, NoPriceDataError, StockNotFoundError
from backend.app.pipeline.jobs import AnalysisBusyError

# 例外 → HTTP 狀態碼（Starlette 依例外的 MRO 找 handler，子類別也適用）
ERROR_STATUS = {
    InvalidStockIdError: 422,
    WatchlistAlreadyExistsError: 409,
    WatchlistNotFoundError: 404,
    ReportNotFoundError: 404,
    StockNotFoundError: 404,
    NoPriceDataError: 422,
    DataSourceError: 502,
    FinMindClientError: 502,
    AnalysisBusyError: 409,
    ActionNotFoundError: 404,
    ActionNotPendingError: 409,
    ActionExpiredError: 410,
    ChatInputError: 422,
    ChatNotConfiguredError: 503,
    ChatLLMError: 502,
}


def register_error_handlers(app: FastAPI) -> None:
    for exc_type, status in ERROR_STATUS.items():
        async def handler(request: Request, exc: Exception, status: int = status) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc), "error": type(exc).__name__})

        app.add_exception_handler(exc_type, handler)


def register_json_only_post(app: FastAPI) -> None:
    """POST 必須是 application/json：跨站的表單 / text/plain「簡單請求」不需 preflight，
    若不擋，惡意網頁可在背景觸發分析、花費 OpenAI 額度。"""

    @app.middleware("http")
    async def json_only_post(request: Request, call_next):
        content_type = request.headers.get("content-type", "")
        if request.method == "POST" and not content_type.lower().startswith("application/json"):
            return JSONResponse(
                status_code=415,
                content={"detail": "POST 請求必須使用 Content-Type: application/json", "error": "UnsupportedMediaType"},
            )
        return await call_next(request)


def session_factory_of(request: Request):
    return request.app.state.session_factory or get_session_factory()


def get_session(request: Request) -> Iterator[Session]:
    with session_factory_of(request)() as session:
        yield session


def analyze_and_save_of(request: Request):
    """分析單檔並存檔（手動分析端點與聊天確認共用）。"""
    analyzer = request.app.state.analyzer
    factory = session_factory_of(request)

    def run(stock_id: str):
        result = analyzer(stock_id)
        with factory() as session:
            return crud.save_report(session, result)

    return run


def tool_context(request: Request, session: Session) -> ToolContext:
    state = request.app.state
    return ToolContext(
        session=session, stock_lookup=state.stock_lookup, quote_provider=state.quote_provider,
        run_analysis=lambda stock_id: state.jobs.run_single(stock_id, analyze_and_save_of(request)),
    )
