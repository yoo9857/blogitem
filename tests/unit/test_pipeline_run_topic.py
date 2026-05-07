"""PipelineService.run_topic_stage — 단계 전이 + 산출물 + 실패 처리."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import blogitem.pipeline.models  # noqa: F401
from blogitem.ai.base import LlmResponse
from blogitem.db import Base
from blogitem.pipeline.artifacts import ArtifactStore
from blogitem.pipeline.models import Artifact, Pipeline
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


@pytest.fixture
def artifact_store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def prompt_lib() -> MagicMock:
    """``PromptLibrary`` mock — system/user 튜플 반환."""
    lib = MagicMock()
    lib.topic.return_value = ("system text", "user text")
    return lib


def _success_llm(text: str = '{"series_title": "test"}') -> MagicMock:
    """``complete`` 가 성공 응답을 반환하는 LlmClient mock."""
    llm = MagicMock()
    llm.complete.return_value = LlmResponse(
        text=text,
        model="claude-opus-4-7",
        input_tokens=100,
        output_tokens=200,
    )
    return llm


# ── 성공 케이스 ────────────────────────────────────────────────────────────────


class TestRunTopicSuccess:
    def test_pending_topic_advances_to_image_awaiting_input(
        self,
        service: PipelineService,
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
        session_factory: sessionmaker[Session],
    ) -> None:
        pipeline_dto = service.create_pipeline(topic="test topic")

        result = service.run_topic_stage(
            pipeline_dto.id,
            llm=_success_llm(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
            lecture_count=10,
        )

        assert result.success is True
        assert result.next_stage == Stage.IMAGE
        assert result.next_status == Status.AWAITING_INPUT
        assert result.error is None
        assert result.input_tokens == 100

        # DB 상태 검증
        with session_factory() as s:
            p = s.get(Pipeline, pipeline_dto.id)
            assert p is not None
            assert Stage(p.current_stage) == Stage.IMAGE
            assert Status(p.status) == Status.AWAITING_INPUT

    def test_artifact_saved_with_correct_metadata(
        self,
        service: PipelineService,
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
        session_factory: sessionmaker[Session],
    ) -> None:
        p = service.create_pipeline(topic="topic-x")

        result = service.run_topic_stage(
            p.id,
            llm=_success_llm(text='{"k": "v"}'),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
        )

        # 디스크 파일 존재
        abs_path = artifact_store.absolute_path(result.artifact_rel_path or "")
        assert abs_path.is_file()
        assert abs_path.read_text(encoding="utf-8") == '{"k": "v"}'

        # DB Artifact row 존재
        with session_factory() as s:
            artifacts = (
                s.query(Artifact)
                .filter(Artifact.pipeline_id == p.id, Artifact.stage == Stage.TOPIC)
                .all()
            )
            assert len(artifacts) == 1
            assert artifacts[0].kind == "text"
            assert artifacts[0].mime == "text/plain; charset=utf-8"
            assert artifacts[0].size == len('{"k": "v"}')

    def test_uses_series_topic_for_prompt(
        self,
        service: PipelineService,
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        series = service.create_series_with_pipelines(
            topic="C언어 20강", lecture_count=3
        )
        pipelines = service.list_pipelines()
        first = next(p for p in pipelines if p.position == 1)

        service.run_topic_stage(
            first.id,
            llm=_success_llm(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
            lecture_count=20,
        )

        prompt_lib.topic.assert_called_once_with(topic="C언어 20강", lecture_count=20)


# ── 실패 케이스 ────────────────────────────────────────────────────────────────


class TestRunTopicFailure:
    def test_llm_failure_marks_pipeline_failed(
        self,
        service: PipelineService,
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
        session_factory: sessionmaker[Session],
    ) -> None:
        p = service.create_pipeline(topic="x")

        llm = MagicMock()
        llm.complete.side_effect = RuntimeError("Claude exploded")

        result = service.run_topic_stage(
            p.id,
            llm=llm,
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
        )

        assert result.success is False
        assert "Claude exploded" in (result.error or "")

        with session_factory() as s:
            row = s.get(Pipeline, p.id)
            assert row is not None
            assert Status(row.status) == Status.FAILED
            # 단계는 그대로 TOPIC (실패해도 다음으로 안 넘어감)
            assert Stage(row.current_stage) == Stage.TOPIC

    def test_wrong_stage_rejected(
        self,
        service: PipelineService,
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
        session_factory: sessionmaker[Session],
    ) -> None:
        from blogitem.pipeline.state_machine import InvalidTransitionError

        p = service.create_pipeline(topic="x")

        # 강제로 stage 를 IMAGE 로 (TOPIC 아님)
        with session_factory() as s:
            row = s.get(Pipeline, p.id)
            assert row is not None
            row.current_stage = Stage.IMAGE
            s.commit()

        with pytest.raises(InvalidTransitionError):
            service.run_topic_stage(
                p.id,
                llm=_success_llm(),
                prompt_lib=prompt_lib,
                artifact_store=artifact_store,
            )

    def test_missing_pipeline_raises(
        self,
        service: PipelineService,
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        with pytest.raises(ValueError, match="not found"):
            service.run_topic_stage(
                99999,
                llm=_success_llm(),
                prompt_lib=prompt_lib,
                artifact_store=artifact_store,
            )
