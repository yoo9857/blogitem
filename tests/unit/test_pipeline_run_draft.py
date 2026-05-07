"""PipelineService.run_draft_stage — TOPIC 산출물 + 이미지 기반 초고 작성."""

from __future__ import annotations

import json
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
from blogitem.pipeline.models import Artifact, Pipeline, Series
from blogitem.pipeline.service import PipelineService
from blogitem.pipeline.stages import Stage, Status
from blogitem.pipeline.state_machine import InvalidTransitionError


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
    lib = MagicMock()
    lib.draft.return_value = ("draft sys", "draft user")
    return lib


def _llm_response(text: str = "# 초고\n\n본문") -> MagicMock:
    llm = MagicMock()
    llm.complete.return_value = LlmResponse(
        text=text, model="claude-opus-4-7", input_tokens=50, output_tokens=300
    )
    return llm


def _setup_pipeline_at_draft(
    session_factory: sessionmaker[Session],
    artifact_store: ArtifactStore,
    *,
    series_topic: str = "C언어 20강",
    position: int = 1,
    n_images: int = 2,
    curriculum: dict | None = None,
) -> int:
    """파이프라인을 DRAFT 단계로 셋업 — TOPIC 산출물 + 이미지 N장."""
    if curriculum is None:
        curriculum = {
            "series_title": series_topic,
            "lectures": [
                {
                    "position": i,
                    "title": f"{i}강: 주제",
                    "summary": f"{i}강 요약",
                    "learning_outcomes": ["a", "b"],
                    "key_concepts": ["c", "d"],
                    "estimated_reading_min": 8,
                }
                for i in range(1, 21)
            ],
        }

    with session_factory() as s:
        series = Series(topic=series_topic, status="active")
        s.add(series)
        s.flush()
        pipeline = Pipeline(
            series_id=series.id,
            position=position,
            slug="test",
            idempotency_key=f"test:{position}",
            current_stage=Stage.DRAFT,
            status=Status.PENDING,
        )
        s.add(pipeline)
        s.flush()
        pipeline_id = pipeline.id

        # TOPIC 산출물 (JSON) 디스크 + DB
        topic_record = artifact_store.save_text(
            pipeline_id=pipeline_id,
            stage=Stage.TOPIC,
            text=json.dumps(curriculum, ensure_ascii=False),
            ext=".json",
        )
        s.add(
            Artifact(
                pipeline_id=pipeline_id,
                stage=Stage.TOPIC,
                kind="text",
                path=topic_record.rel_path,
                sha256=topic_record.sha256,
                size=topic_record.size,
                mime=topic_record.mime,
            )
        )

        # 이미지 N장 (가짜 PNG)
        for i in range(n_images):
            img_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
            img_record = artifact_store.save_bytes(
                pipeline_id=pipeline_id,
                stage=Stage.IMAGE,
                kind="image",
                data=img_data,
                ext=".png",
                mime="image/png",
            )
            s.add(
                Artifact(
                    pipeline_id=pipeline_id,
                    stage=Stage.IMAGE,
                    kind="image",
                    path=img_record.rel_path,
                    sha256=img_record.sha256,
                    size=img_record.size,
                    mime=img_record.mime,
                )
            )

        s.commit()
    return pipeline_id


# ── 성공 케이스 ────────────────────────────────────────────────────────────────


class TestRunDraftSuccess:
    def test_advances_to_humanize_awaiting_input(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        pid = _setup_pipeline_at_draft(session_factory, artifact_store)

        result = service.run_draft_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
        )

        assert result.success is True
        assert result.next_stage == Stage.HUMANIZE
        assert result.next_status == Status.AWAITING_INPUT

        with session_factory() as s:
            p = s.get(Pipeline, pid)
            assert Stage(p.current_stage) == Stage.HUMANIZE
            assert Status(p.status) == Status.AWAITING_INPUT

    def test_uses_lecture_meta_for_position(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        pid = _setup_pipeline_at_draft(
            session_factory, artifact_store, position=3
        )
        service.run_draft_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
        )

        # prompt_lib.draft 가 position=3 의 lecture_meta 로 호출됐는지 검증
        kwargs = prompt_lib.draft.call_args.kwargs
        assert kwargs["lecture_meta"]["position"] == 3
        assert "3강" in kwargs["lecture_meta"]["title"]

    def test_image_descriptions_passed_to_prompt(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        pid = _setup_pipeline_at_draft(
            session_factory, artifact_store, n_images=3
        )
        service.run_draft_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
        )

        kwargs = prompt_lib.draft.call_args.kwargs
        descriptions = kwargs["image_descriptions"]
        assert len(descriptions) == 3
        assert all("이미지" in d for d in descriptions)

    def test_artifact_saved_as_markdown(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        pid = _setup_pipeline_at_draft(session_factory, artifact_store)
        result = service.run_draft_stage(
            pid,
            llm=_llm_response(text="# 새 초고"),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
        )
        assert result.artifact_rel_path is not None
        assert result.artifact_rel_path.endswith(".md")
        path = artifact_store.absolute_path(result.artifact_rel_path)
        assert path.read_text(encoding="utf-8") == "# 새 초고"


# ── 실패 케이스 ────────────────────────────────────────────────────────────────


class TestRunDraftFailure:
    def test_missing_topic_artifact_marks_failed(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        # TOPIC 산출물 없는 상태에서 DRAFT 시도
        with session_factory() as s:
            p = Pipeline(
                series_id=None,
                position=1,
                slug="x",
                idempotency_key="x:1",
                current_stage=Stage.DRAFT,
                status=Status.PENDING,
            )
            s.add(p)
            s.commit()
            pid = p.id

        result = service.run_draft_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
        )
        assert result.success is False
        assert "TOPIC" in (result.error or "")

        with session_factory() as s:
            p = s.get(Pipeline, pid)
            assert Status(p.status) == Status.FAILED

    def test_position_out_of_range_marks_failed(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        # 커리큘럼은 5개인데 pipeline.position 이 10
        small_curriculum = {
            "lectures": [{"position": i, "title": f"{i}강"} for i in range(1, 6)]
        }
        pid = _setup_pipeline_at_draft(
            session_factory, artifact_store, position=10, curriculum=small_curriculum
        )

        result = service.run_draft_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
        )
        assert result.success is False
        assert "position" in (result.error or "").lower() or "10" in (result.error or "")

    def test_wrong_stage_rejected(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        # TOPIC 단계인 채로 run_draft 호출
        with session_factory() as s:
            p = Pipeline(
                series_id=None,
                position=1,
                slug="x",
                idempotency_key="x:1",
                current_stage=Stage.TOPIC,
                status=Status.PENDING,
            )
            s.add(p)
            s.commit()
            pid = p.id

        with pytest.raises(InvalidTransitionError):
            service.run_draft_stage(
                pid,
                llm=_llm_response(),
                prompt_lib=prompt_lib,
                artifact_store=artifact_store,
            )

    def test_llm_failure_marks_failed_keeps_stage(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        pid = _setup_pipeline_at_draft(session_factory, artifact_store)

        llm = MagicMock()
        llm.complete.side_effect = RuntimeError("Claude down")

        result = service.run_draft_stage(
            pid,
            llm=llm,
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
        )
        assert result.success is False
        with session_factory() as s:
            p = s.get(Pipeline, pid)
            assert Status(p.status) == Status.FAILED
            assert Stage(p.current_stage) == Stage.DRAFT  # 단계는 그대로
