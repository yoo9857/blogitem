"""Watchdog detector — Stuck 파이프라인 + Token 만료."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import blogitem.pipeline.models  # noqa: F401
from blogitem.db import Base
from blogitem.pipeline.models import Pipeline
from blogitem.pipeline.stages import Stage, Status
from blogitem.watchdog.monitor import (
    StuckPipelineDetector,
    TokenExpiryDetector,
)


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        f"sqlite:///{tmp_path}/test.db",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    engine.dispose()


def _add_pipeline(
    session_factory: sessionmaker[Session],
    *,
    stage: Stage,
    status: Status,
    updated_hours_ago: float = 0.0,
) -> int:
    """파이프라인 1개 추가. ``updated_at`` 을 과거 시점으로 강제."""
    when = datetime.now() - timedelta(hours=updated_hours_ago)
    with session_factory() as s:
        p = Pipeline(
            series_id=None,
            position=1,
            slug="x",
            idempotency_key=f"x:{stage.value}:{updated_hours_ago}",
            current_stage=stage,
            status=status,
            created_at=when,
            updated_at=when,
        )
        s.add(p)
        s.commit()
        return p.id


# ── StuckPipelineDetector ──────────────────────────────────────────────────────


class TestStuckPipelineDetector:
    def test_finds_awaiting_input_over_threshold(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        _add_pipeline(
            session_factory,
            stage=Stage.IMAGE,
            status=Status.AWAITING_INPUT,
            updated_hours_ago=30,
        )
        detector = StuckPipelineDetector(session_factory)
        stuck = detector.find_stuck(hours=24)
        assert len(stuck) == 1
        assert stuck[0].status == Status.AWAITING_INPUT
        assert stuck[0].idle_hours >= 24

    def test_recent_awaiting_input_not_stuck(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        _add_pipeline(
            session_factory,
            stage=Stage.IMAGE,
            status=Status.AWAITING_INPUT,
            updated_hours_ago=10,
        )
        detector = StuckPipelineDetector(session_factory)
        assert detector.find_stuck(hours=24) == []

    def test_failed_always_returned(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        # 방금 만든 FAILED 파이프라인도 stuck 으로 간주
        _add_pipeline(
            session_factory,
            stage=Stage.TOPIC,
            status=Status.FAILED,
            updated_hours_ago=0.1,
        )
        detector = StuckPipelineDetector(session_factory)
        stuck = detector.find_stuck(hours=24)
        assert len(stuck) == 1
        assert stuck[0].status == Status.FAILED

    def test_done_not_stuck(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        _add_pipeline(
            session_factory,
            stage=Stage.PUBLISH,
            status=Status.DONE,
            updated_hours_ago=100,
        )
        detector = StuckPipelineDetector(session_factory)
        assert detector.find_stuck(hours=24) == []

    def test_pending_not_stuck(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        # PENDING 은 자동 단계 대기 — Watchdog 대상 아님 (orchestrator 가 처리해야)
        _add_pipeline(
            session_factory,
            stage=Stage.TOPIC,
            status=Status.PENDING,
            updated_hours_ago=100,
        )
        detector = StuckPipelineDetector(session_factory)
        assert detector.find_stuck(hours=24) == []

    def test_negative_hours_rejected(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        detector = StuckPipelineDetector(session_factory)
        with pytest.raises(ValueError):
            detector.find_stuck(hours=-1)

    def test_idle_hours_calculated(
        self, session_factory: sessionmaker[Session]
    ) -> None:
        _add_pipeline(
            session_factory,
            stage=Stage.HUMANIZE,
            status=Status.AWAITING_INPUT,
            updated_hours_ago=72,
        )
        detector = StuckPipelineDetector(session_factory)
        stuck = detector.find_stuck(hours=24)
        assert len(stuck) == 1
        # ±2시간 마진
        assert 70 <= stuck[0].idle_hours <= 74


# ── TokenExpiryDetector ────────────────────────────────────────────────────────


class TestTokenExpiryDetector:
    def test_returns_none_when_no_token(self) -> None:
        store = MagicMock()
        store.days_until_refresh_expiry.return_value = None
        d = TokenExpiryDetector(store)
        assert d.days_until_expiry() is None
        assert d.is_expiring_soon() is False

    def test_returns_days_left(self) -> None:
        store = MagicMock()
        store.days_until_refresh_expiry.return_value = 365
        d = TokenExpiryDetector(store)
        assert d.days_until_expiry() == 365
        assert d.is_expiring_soon(threshold_days=30) is False

    def test_expiring_soon_below_threshold(self) -> None:
        store = MagicMock()
        store.days_until_refresh_expiry.return_value = 15
        d = TokenExpiryDetector(store)
        assert d.is_expiring_soon(threshold_days=30) is True

    def test_at_threshold_is_expiring(self) -> None:
        store = MagicMock()
        store.days_until_refresh_expiry.return_value = 30
        d = TokenExpiryDetector(store)
        assert d.is_expiring_soon(threshold_days=30) is True

    def test_zero_days_expiring(self) -> None:
        store = MagicMock()
        store.days_until_refresh_expiry.return_value = 0
        d = TokenExpiryDetector(store)
        assert d.is_expiring_soon() is True
