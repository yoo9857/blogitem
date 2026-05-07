"""PipelineService — 시리즈/파이프라인 CRUD."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import blogitem.pipeline.models  # noqa: F401 — Base.metadata 등록
from blogitem.db import Base
from blogitem.pipeline.dto import SeriesDTO
from blogitem.pipeline.service import PipelineService, slugify
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


# ── slugify ────────────────────────────────────────────────────────────────


class TestSlugify:
    def test_english_basic(self) -> None:
        assert slugify("Hello World") == "hello-world"

    def test_special_chars_collapse(self) -> None:
        assert slugify("a!@#b...c") == "a-b-c"

    def test_korean_falls_back(self) -> None:
        # 한국어는 영문/숫자 외 모두 제거 → 빈 결과 → 'topic' 폴백
        assert slugify("C언어") == "c"
        assert slugify("안녕하세요") == "topic"


# ── 시리즈 + 파이프라인 일괄 생성 ─────────────────────────────────────────────


class TestCreateSeries:
    def test_creates_series_and_n_pipelines(self, service: PipelineService) -> None:
        result: SeriesDTO = service.create_series_with_pipelines(
            topic="C언어 20강",
            lecture_count=20,
        )
        assert result.id > 0
        assert result.topic == "C언어 20강"
        assert result.pipeline_count == 20

        pipelines = service.list_pipelines()
        assert len(pipelines) == 20
        assert {p.position for p in pipelines} == set(range(1, 21))
        assert all(p.series_id == result.id for p in pipelines)
        assert all(p.current_stage == Stage.TOPIC for p in pipelines)
        assert all(p.status == Status.PENDING for p in pipelines)

    def test_pipeline_slugs_unique_per_position(self, service: PipelineService) -> None:
        service.create_series_with_pipelines(topic="C lang course", lecture_count=5)
        pipelines = service.list_pipelines()
        slugs = {p.slug for p in pipelines}
        assert len(slugs) == 5  # 모두 서로 다른 슬러그

    def test_idempotency_keys_unique(self, service: PipelineService) -> None:
        service.create_series_with_pipelines(topic="x", lecture_count=3)
        # 같은 주제로 또 생성해도 series_id 가 다르므로 idempotency_key 도 다름
        service.create_series_with_pipelines(topic="x", lecture_count=3)
        assert len(service.list_pipelines()) == 6

    def test_empty_topic_rejected(self, service: PipelineService) -> None:
        with pytest.raises(ValueError, match="topic"):
            service.create_series_with_pipelines(topic="   ", lecture_count=5)

    def test_count_out_of_range_rejected(self, service: PipelineService) -> None:
        with pytest.raises(ValueError, match="강의 수"):
            service.create_series_with_pipelines(topic="x", lecture_count=0)
        with pytest.raises(ValueError, match="강의 수"):
            service.create_series_with_pipelines(topic="x", lecture_count=101)


# ── 단일 파이프라인 ────────────────────────────────────────────────────────


class TestCreatePipeline:
    def test_single_pipeline_no_series(self, service: PipelineService) -> None:
        p = service.create_pipeline(topic="one-off post")
        assert p.id > 0
        assert p.series_id is None
        assert p.current_stage == Stage.TOPIC

    def test_get_returns_dto(self, service: PipelineService) -> None:
        p = service.create_pipeline(topic="x")
        fetched = service.get_pipeline(p.id)
        assert fetched is not None
        assert fetched.id == p.id
        assert fetched.slug == "x"

    def test_get_missing_returns_none(self, service: PipelineService) -> None:
        assert service.get_pipeline(99999) is None


# ── 시리즈 목록 ────────────────────────────────────────────────────────────


class TestListSeries:
    def test_includes_pipeline_count(self, service: PipelineService) -> None:
        service.create_series_with_pipelines(topic="A", lecture_count=3)
        service.create_series_with_pipelines(topic="B", lecture_count=5)

        result = service.list_series()
        assert len(result) == 2
        # id desc — 최신이 먼저
        topics_to_count = {s.topic: s.pipeline_count for s in result}
        assert topics_to_count == {"A": 3, "B": 5}
