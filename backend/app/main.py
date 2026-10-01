"""FastAPI 入口。

規格（Stage 7 spec，2026-10-01 使用者確認安全性與全清單背景執行）
==============================================================

``create_app(settings=None, session_factory=None, analyzer=None, stock_lookup=None, jobs=None) -> FastAPI``
各相依皆可注入（測試不打 FinMind / OpenAI、不碰真實資料庫）；不帶時用統一設定。
資料庫連線**第一次使用時才建立**，import 本模組不會產生資料庫檔案。

啟動：``uv run uvicorn backend.app.main:app``（uvicorn 預設只綁 127.0.0.1，**不要加 --host 0.0.0.0**）

安全性（第一輪風險檢討）
------------------------
- ``TrustedHostMiddleware``：只接受 ``settings.api_allowed_hosts`` 的 Host 標頭（預設 127.0.0.1、localhost），
  擋 DNS rebinding；不符 → 400
- 不開 CORS：前端（Stage 9）透過 Vite dev server proxy 呼叫，同源
- 所有 POST 必須是 ``Content-Type: application/json`` → 否則 415。瀏覽器跨站送出的「簡單請求」
  （表單、text/plain）因此無法觸發分析、花費 OpenAI 額度

端點
----
- ``GET  /api/health``：資料庫可連線 → {"status": "ok", "database": "ok"}
- ``GET  /api/watchlist``：啟用中清單
- ``POST /api/watchlist`` {stock_id}：201；代號格式錯 422；已在清單 409；查無代號 404；FinMind 錯誤 502
  （先檢查是否已在清單，避免不必要的 FinMind 呼叫；股票名稱由 FinMind 股票基本資料取得）
- ``DELETE /api/watchlist/{stock_id}``：200 回傳被移除的項目；不在清單 404
- ``GET  /api/reports/latest``：清單中每檔的最新報告（摘要，不含訊號）
- ``GET  /api/reports/{stock_id}/latest``：最新報告（含訊號）；沒有 → 404
- ``GET  /api/reports/{stock_id}/history?start=&end=&all_runs=``：歷史（摘要），預設每天一份
- ``POST /api/analysis/run``：202，背景分析整份清單並存檔；已有分析在執行 → 409
- ``GET  /api/analysis/status``：最近一次全清單分析的進度
- ``POST /api/analysis/run/{stock_id}``：同步分析單檔並存檔，回傳報告（含訊號）；忙碌 409、
  查無代號 404、無股價 422、FinMind 錯誤 502
錯誤回應格式：{"detail": 說明, "error": 例外類別名}
"""

from __future__ import annotations

from typing import Callable

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from backend.app.api import routes_analysis, routes_reports, routes_watchlist
from backend.app.api.deps import register_error_handlers, register_json_only_post
from backend.app.config import Settings, get_settings
from backend.app.data_sources.finmind_client import create_finmind_client
from backend.app.data_sources.stock_profile import StockProfile, resolve_stock_profile
from backend.app.pipeline.analyze_stock import analyze_stock
from backend.app.pipeline.jobs import AnalysisJobManager


def create_app(
    settings: Settings | None = None,
    session_factory=None,
    analyzer: Callable | None = None,
    stock_lookup: Callable[[str], StockProfile | None] | None = None,
    jobs: AnalysisJobManager | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    def default_analyzer(stock_id: str):
        return analyze_stock(stock_id, settings=settings)

    def default_stock_lookup(stock_id: str) -> StockProfile | None:
        return resolve_stock_profile(create_finmind_client(settings).get_stock_info(), stock_id)

    app = FastAPI(title="StockAgent API")
    app.state.settings = settings
    app.state.session_factory = session_factory  # None → 第一次使用時才依設定建立
    app.state.analyzer = analyzer or default_analyzer
    app.state.stock_lookup = stock_lookup or default_stock_lookup
    app.state.jobs = jobs or AnalysisJobManager()

    register_error_handlers(app)
    register_json_only_post(app)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.api_allowed_hosts)
    for router in (routes_watchlist.router, routes_reports.router, routes_analysis.router):
        app.include_router(router)
    return app


app = create_app()
