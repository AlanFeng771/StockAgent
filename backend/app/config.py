"""全專案設定統一管理處。

所有環境相關/可調整的執行參數都定義在 ``Settings``，值來源優先順序：
環境變數 > 專案根目錄的 ``.env`` > 這裡的預設值（欄位名對應大寫環境變數，
例如 ``cache_ttl_seconds`` ↔ ``CACHE_TTL_SECONDS``）。程式其他地方不要自行
讀 ``os.environ`` 或寫死這些數值，一律透過 ``get_settings()`` 取得。

例外：分析規則的門檻值（連續買超天數、YoY門檻等）屬於分析邏輯而非執行環境，
依計畫集中在 ``signals/config.py``。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 外部服務
    finmind_api_token: str | None = None
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    openai_temperature: float = 0.2      # 偏低以提高同一份事實重跑時結論的一致性
    openai_timeout_seconds: float = 60.0
    openai_repair_attempts: int = 1      # 報告有價格警告時，回饋給 LLM 自動修正的最多次數（0 = 不修正）

    # 聊天（Stage 8；行為定義見 chat/chat_service.py）
    chat_model: str = "gpt-4o"
    chat_temperature: float = 0.3
    chat_max_tool_rounds: int = 5          # 一次回答最多連續呼叫工具的輪數，超過則要求 LLM 直接回覆
    chat_summary_model: str = "gpt-4o-mini"
    chat_recent_messages: int = 10         # 總結後保留的最近原文則數
    chat_summary_every: int = 20           # 每累積 N 則新訊息就把較舊的併入摘要
    chat_action_ttl_minutes: int = 10      # 危險動作待確認的有效時間
    chat_message_max_chars: int = 2000

    # 排程（Stage 6，目前延後）
    daily_analysis_hour: int = 17
    daily_analysis_minute: int = 0

    # API：只接受這些 Host 標頭（擋 DNS rebinding；搭配 uvicorn 預設只綁 127.0.0.1）
    api_allowed_hosts: list[str] = ["127.0.0.1", "localhost"]

    # 資料庫
    database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'stockagent.db').as_posix()}"

    # FinMind 快取（行為定義見 data_sources/cache.py）
    cache_dir: Path = PROJECT_ROOT / "data" / "cache"
    cache_ttl_seconds: int = 3600       # 近期資料有效秒數
    cache_final_after_days: int = 3     # 區間結束日早於今天N天以上視為已定案
    cache_max_age_days: int = 14        # 超過N天未更新的快取檔自動刪除；需 >= 新聞回溯天數

    @field_validator("cache_dir")
    @classmethod
    def _resolve_relative_to_project_root(cls, value: Path) -> Path:
        # 相對路徑一律以專案根目錄為基準，不受執行時所在目錄影響
        return value if value.is_absolute() else PROJECT_ROOT / value


@lru_cache
def get_settings() -> Settings:
    return Settings()
