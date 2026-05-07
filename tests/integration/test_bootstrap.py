"""부트스트랩 단위 — Settings / 로깅 / DB 마이그레이션."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_settings_load_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``.env`` 없는 상태에서도 Settings 로드 OK + 기본값 적용."""
    import os

    monkeypatch.chdir(tmp_path)
    # 외부 BLOGITEM_* 환경변수가 기본값 검증을 흔들지 않도록 격리
    for key in list(os.environ):
        if key.startswith("BLOGITEM_"):
            monkeypatch.delenv(key, raising=False)

    from blogitem.config import load_settings

    s = load_settings()

    assert s.dry_run is True
    assert s.oauth_callback_host == "127.0.0.1"
    assert s.oauth_callback_port == 8765
    assert s.claude_model_primary.startswith("claude-")


def test_logging_configures_without_file(tmp_path: Path) -> None:
    """log_dir 가 없는 상태에서도 logging 초기화 성공 + 호출 OK."""
    from blogitem.log import configure_logging, get_logger

    configure_logging(level="debug", log_dir=tmp_path / "logs")
    log = get_logger("test")
    # 호출 자체가 raise 하지 않으면 성공.
    log.info("test_event", key="value")
    log.warning("warn_event")


def test_alembic_migration_creates_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Alembic upgrade 가 5 테이블을 생성하는지 — 격리된 DB 에서 검증."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("BLOGITEM_DB_PATH", str(db_path))

    from blogitem.app import _run_migrations
    from blogitem.db import make_engine
    from sqlalchemy import inspect

    _run_migrations(db_path)

    engine = make_engine(db_path)
    tables = set(inspect(engine).get_table_names())
    assert {"series", "pipelines", "pipeline_stages", "artifacts", "approvals"} <= tables
    # alembic_version 도 있어야 함
    assert "alembic_version" in tables
