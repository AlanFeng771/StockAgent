"""單股分析 pipeline：抓資料 → 規則訊號 → LLM 報告。供 CLI / 排程 / API / 聊天共用，不耦合 DB。

規格（Stage 4 spec）
====================

``analyze_stock(stock_id, today=None, finmind_client=None, openai_client=None, settings=None) -> AnalysisResult``

流程
----
1. ``fetch_stock_raw_data``（Stage 1，依 signals/config.py 回溯期間）
2. ``build_stock_signals``（Stage 2）
3. ``generate_report``（Stage 3）——LLM 出錯不丟例外，結果放在 ``report.llm_status``
``today`` 預設為今天；``finmind_client`` / ``openai_client`` / ``settings`` 可注入（測試用），
不帶時依統一設定建立（FinMind 含快取）。

分析日期
--------
``analysis_date`` = 抓到的股價最新一筆日期（Stage 6 排程延後期間的決定：手動觸發不依賴交易日曆，
盤中或假日觸發時自然對應到最近一個有資料的交易日）。

例外（上層排程 / API 依此決定處理方式）
--------------------------------------
- ``AnalysisError``：本模組所有例外的基底
- ``StockNotFoundError``：股票基本資料查無此代號**且**查無股價（例如打錯代號）→ API 可回 404
- ``NoPriceDataError``：查得到代號但沒有股價資料（例如已下市、長期停牌）→ 無法分析
- ``DataSourceError``：FinMind 呼叫失敗（額度、token、API 錯誤），``__cause__`` 保留原始
  ``FinMindClientError``，可由 ``.source_error`` 取得以區分額度用完或 token 問題
股價資料不足以計算技術指標（新上市）不是例外：照常產出，缺的面向寫在 ``signals.unavailable``，
LLM 依 prompt 規則在報告中說明資料限制。

輸出 ``AnalysisResult``
-----------------------
stock_id、analysis_date、generated_at（產生時間）、signals（StockSignals）、report（ReportResult）
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel

from backend.app.config import Settings, get_settings
from backend.app.data_sources.finmind_client import FinMindClientError, create_finmind_client
from backend.app.llm.report_generator import ReportResult, generate_report
from backend.app.pipeline.fetch import fetch_stock_raw_data
from backend.app.signals.signal_builder import StockSignals, build_stock_signals


class AnalysisError(Exception):
    """pipeline 例外基底。"""


class StockNotFoundError(AnalysisError):
    """查無此股票代號。"""


class NoPriceDataError(AnalysisError):
    """有此代號但沒有股價資料。"""


class DataSourceError(AnalysisError):
    """FinMind 資料來源錯誤。"""

    @property
    def source_error(self) -> FinMindClientError | None:
        return self.__cause__ if isinstance(self.__cause__, FinMindClientError) else None


class AnalysisResult(BaseModel):
    stock_id: str
    analysis_date: date
    generated_at: datetime
    signals: StockSignals
    report: ReportResult


def analyze_stock(
    stock_id: str,
    today: date | None = None,
    finmind_client: Any = None,
    openai_client: Any = None,
    settings: Settings | None = None,
) -> AnalysisResult:
    settings = settings or get_settings()
    today = today or date.today()
    try:
        finmind_client = finmind_client or create_finmind_client(settings)
        raw = fetch_stock_raw_data(finmind_client, stock_id, today)
    except FinMindClientError as exc:
        raise DataSourceError(f"{stock_id} 資料抓取失敗：{exc}") from exc

    signals = build_stock_signals(stock_id, raw)
    if signals.data_freshness["price"] is None:
        if signals.profile is None:
            raise StockNotFoundError(f"查無股票代號 {stock_id}")
        raise NoPriceDataError(f"{stock_id} {signals.profile.stock_name} 沒有股價資料")

    report = generate_report(signals, client=openai_client, settings=settings)
    return AnalysisResult(
        stock_id=stock_id, analysis_date=signals.data_freshness["price"], generated_at=datetime.now(),
        signals=signals, report=report,
    )
