"""Orchestrator — find_next_automatic_pending 로직 단위 테스트."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import blogitem.pipeline.models  # noqa: F401
from blogitem.db import Base
from blogitem.pipeline.models import Pipeline
from blogitem.pipeline.orchestrator import find_next_automatic_pending
from blogitem.pipeline.service import PipelineService
from blogitem.pipeline.stages import Stage, Status


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


@pytest.fixture
def service(session_factory: sessionmaker[Session]) -> PipelineService:
    return PipelineService(session_factory)


def _add_pipeline(
    session_factory: sessionmaker[Session],
    *,
    stage: Stage,
    status: Status,
    slug: str = "x",
) -> int:
    with session_factory() as s:
        p = Pipeline(
            series_id=None,
            position=1,
            slug=slug,
            idempotency_key=f"{slug}:{stage.value}:{status.value}",
            current_stage=stage,
            status=status,
        )
        s.add(p)
        s.commit()
        return p.id


class TestFindNextPending:
    def test_returns_none_when_no_pipelines(self, service: PipelineService) -> None:
        assert find_next_automatic_pending(service) is None

    def test_finds_topic_pending(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        _add_pipeline(
            session_factory, stage=Stage.TOPIC, status=Status.PENDING, slug="t"
        )
        result = find_next_automatic_pending(service)
        assert result is not None
        assert result.current_stage == Stage.TOPIC
        assert result.status == Status.PENDING

    def test_finds_draft_pending(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        _add_pipeline(
            session_factory, stage=Stage.DRAFT, status=Status.PENDING, slug="d"
        )
        result = find_next_automatic_pending(service)
        assert result is not None
        assert result.current_stage == Stage.DRAFT

    def test_finds_publish_pending(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        _add_pipeline(
            session_factory, stage=Stage.PUBLISH, status=Status.PENDING, slug="p"
        )
        result = find_next_automatic_pending(service)
        assert result is not None
        assert result.current_stage == Stage.PUBLISH

    def test_skips_image_awaiting_input(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        # IMAGE 는 자동 단계 아님 — 사람 업로드 대기 중
        _add_pipeline(
            session_factory,
            stage=Stage.IMAGE,
            status=Status.AWAITING_INPUT,
            slug="i",
        )
        assert find_next_automatic_pending(service) is None

    def test_skips_humanize_awaiting_input(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        _add_pipeline(
            session_factory,
            stage=Stage.HUMANIZE,
            status=Status.AWAITING_INPUT,
            slug="h",
        )
        assert find_next_automatic_pending(service) is None

    def test_skips_confirm_awaiting_review(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        _add_pipeline(
            session_factory,
            stage=Stage.CONFIRM,
            status=Status.AWAITING_REVIEW,
            slug="c",
        )
        assert find_next_automatic_pending(service) is None

    def test_skips_running(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        _add_pipeline(
            session_factory, stage=Stage.TOPIC, status=Status.RUNNING, slug="r"
        )
        assert find_next_automatic_pending(service) is None

    def test_skips_failed(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        _add_pipeline(
            session_factory, stage=Stage.TOPIC, status=Status.FAILED, slug="f"
        )
        # FAILED 는 사용자 수동 재큐잉 필요 — orchestrator 가 자동 재시도 안 함
        assert find_next_automatic_pending(service) is None

    def test_skips_done(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        _add_pipeline(
            session_factory, stage=Stage.PUBLISH, status=Status.DONE, slug="o"
        )
        assert find_next_automatic_pending(service) is None

    def test_returns_lowest_id_first(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        # 3개 후보 — 가장 낮은 id 반환 (FIFO)
        id1 = _add_pipeline(
            session_factory, stage=Stage.TOPIC, status=Status.PENDING, slug="a"
        )
        _add_pipeline(
            session_factory, stage=Stage.DRAFT, status=Status.PENDING, slug="b"
        )
        _add_pipeline(
            session_factory, stage=Stage.PUBLISH, status=Status.PENDING, slug="c"
        )
        result = find_next_automatic_pending(service)
        assert result is not None
        assert result.id == id1

    def test_mixed_states_picks_eligible_only(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        _add_pipeline(
            session_factory,
            stage=Stage.IMAGE,
            status=Status.AWAITING_INPUT,
            slug="early",
        )  # id=1, ineligible
        eligible_id = _add_pipeline(
            session_factory,
            stage=Stage.DRAFT,
            status=Status.PENDING,
            slug="ok",
        )  # id=2, eligible
        _add_pipeline(
            session_factory,
            stage=Stage.PUBLISH,
            status=Status.DONE,
            slug="done",
        )  # id=3, ineligible
        result = find_next_automatic_pending(service)
        assert result is not None
        assert result.id == eligible_id
