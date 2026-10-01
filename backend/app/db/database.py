"""SQLite 連線與初始化。

規格（Stage 5 spec）
====================

``create_db_engine(url) -> Engine``
- SQLite 檔案資料庫：自動建立所在資料夾；每個連線設定
  ``journal_mode=WAL``（讀寫可並行，避免 API 讀取時被排程寫入卡住，見第一輪風險檢討）、
  ``busy_timeout=5000``（遇到鎖定先等 5 秒而不是立刻丟 database is locked）、``foreign_keys=ON``
- ``check_same_thread=False``：FastAPI 與排程會在不同執行緒使用連線
- 記憶體資料庫（``sqlite://``，測試用）：用 StaticPool 讓同一個 engine 的所有連線共用同一份資料

``init_db(engine)``：建立所有資料表（MVP 不做 migration；之後若改 schema，再評估導入 Alembic）

``make_session_factory(engine)`` / ``get_session_factory()``：後者依統一設定的 ``database_url`` 建立並快取
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.config import get_settings
from backend.app.db.models import Base


def create_db_engine(url: str) -> Engine:
    parsed = make_url(url)
    in_memory = parsed.get_backend_name() == "sqlite" and parsed.database in (None, "", ":memory:")
    if parsed.get_backend_name() == "sqlite" and not in_memory:
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)

    kwargs = {"connect_args": {"check_same_thread": False}}
    if in_memory:
        kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)

    if parsed.get_backend_name() == "sqlite":
        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            if not in_memory:
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    engine = create_db_engine(get_settings().database_url)
    init_db(engine)
    return make_session_factory(engine)
