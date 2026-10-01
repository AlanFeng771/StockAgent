from __future__ import annotations

from pathlib import Path

from backend.app.config import PROJECT_ROOT, Settings
from backend.app.data_sources.finmind_client import create_finmind_client


def test_defaults_without_env_file(monkeypatch):
    for name in ("FINMIND_API_TOKEN", "OPENAI_API_KEY", "CACHE_MAX_AGE_DAYS"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.finmind_api_token is None
    assert settings.openai_api_key is None
    assert settings.cache_dir == PROJECT_ROOT / "data" / "cache"
    assert settings.cache_ttl_seconds == 3600
    assert settings.cache_final_after_days == 3
    assert settings.cache_max_age_days == 14


def test_env_variables_override_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("FINMIND_API_TOKEN", "abc")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("CACHE_MAX_AGE_DAYS", "30")

    settings = Settings(_env_file=None)

    assert settings.finmind_api_token == "abc"
    assert settings.cache_dir == tmp_path
    assert settings.cache_max_age_days == 30


def test_env_file_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("CACHE_TTL_SECONDS", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("CACHE_TTL_SECONDS=120\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.cache_ttl_seconds == 120


def test_create_finmind_client_uses_cache_settings(tmp_path):
    settings = Settings(_env_file=None, finmind_api_token=None, cache_dir=tmp_path / "c")

    client = create_finmind_client(settings)

    assert client._cache is not None
    assert Path(tmp_path / "c").is_dir()


def test_create_finmind_client_can_disable_cache(tmp_path):
    settings = Settings(_env_file=None, finmind_api_token=None, cache_dir=tmp_path / "c")

    client = create_finmind_client(settings, use_cache=False)

    assert client._cache is None


def test_relative_cache_dir_is_resolved_against_project_root(monkeypatch):
    monkeypatch.setenv("CACHE_DIR", "data/cache")

    settings = Settings(_env_file=None)

    assert settings.cache_dir == PROJECT_ROOT / "data" / "cache"
