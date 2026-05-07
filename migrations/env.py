"""Alembic 런타임 환경.

DB URL 은 ``BLOGITEM_DB_PATH`` 환경변수에서 SQLite 경로로 주입.
모델은 ``blogitem.pipeline.models`` 에서 ``Base.metadata`` 자동 수집.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

import blogitem.pipeline.models  # noqa: F401 — 모델 등록 (autogenerate 용)
from blogitem.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DB URL — 환경변수 우선, 없으면 기본 경로
db_path = Path(os.environ.get("BLOGITEM_DB_PATH", "./data/blogitem.db"))
db_path.parent.mkdir(parents=True, exist_ok=True)
config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """오프라인 모드 — 실제 DB 연결 없이 SQL 만 출력."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER 호환
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """온라인 모드 — 실제 DB 에 ALTER 실행."""
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
