"""SQLAlchemy engine + Session 팩토리."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session


class Base(DeclarativeBase):
    """모든 ORM 모델의 베이스. 도메인 객체는 이 클래스를 상속한다."""


def make_engine(db_path: Path) -> Engine:
    """SQLite 엔진 생성. 부모 디렉토리 자동 생성.

    Notes:
        ``check_same_thread=False`` — QThread 워커가 다른 스레드에서도 세션을
        만들 수 있게. SQLite WAL 모드 + connection-per-thread 패턴이 안전.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{db_path}",
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """세션 팩토리 — 1 트랜잭션 단위로 사용 후 close."""
    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
