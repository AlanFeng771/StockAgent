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

    # 排程（Stage 6，目前延後）
    daily_analysis_hour: int = 17
    daily_analysis_minute: int = 0

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
