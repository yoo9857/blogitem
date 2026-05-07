"""PipelineService.run_publish_stage — Claude HTML 변환 + 채널 게시."""

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
from blogitem.channels.base import PublishError, PublishResult
from blogitem.db import Base
from blogitem.pipeline.artifacts import ArtifactStore
from blogitem.pipeline.models import Approval, Artifact, Pipeline, Series
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
    lib = MagicMock()
    lib.publish.return_value = ("publish sys", "publish user")
    return lib


def _llm_response(text: str = "<h1>제목</h1><p>본문</p>") -> MagicMock:
    llm = MagicMock()
    llm.complete.return_value = LlmResponse(
        text=text, model="claude-opus-4-7", input_tokens=200, output_tokens=400
    )
    return llm


def _success_channel(external_id: str = "logno-12345") -> MagicMock:
    channel = MagicMock()
    channel.publish.return_value = PublishResult(
        channel="naver", external_id=external_id, url=f"https://blog.naver.com/x/{external_id}"
    )
    return channel


def _setup_pipeline_at_publish(
    session_factory: sessionmaker[Session],
    artifact_store: ArtifactStore,
    *,
    position: int = 1,
) -> int:
    """파이프라인을 PUBLISH 단계로 셋업 — TOPIC + IMAGE + HUMANIZE 산출물 모두 있음."""
    curriculum = {
        "lectures": [
            {"position": i, "title": f"{i}강 — 변수와 자료형"} for i in range(1, 11)
        ]
    }

    with session_factory() as s:
        series = Series(topic="C언어 시리즈", status="active")
        s.add(series)
        s.flush()
        p = Pipeline(
            series_id=series.id,
            position=position,
            slug="x",
            idempotency_key=f"x:{position}",
            current_stage=Stage.PUBLISH,
            status=Status.PENDING,
        )
        s.add(p)
        s.flush()
        pid = p.id

        # TOPIC artifact (JSON)
        rec = artifact_store.save_text(
            pipeline_id=pid,
            stage=Stage.TOPIC,
            text=json.dumps(curriculum, ensure_ascii=False),
            ext=".json",
        )
        s.add(
            Artifact(
                pipeline_id=pid, stage=Stage.TOPIC, kind="text",
                path=rec.rel_path, sha256=rec.sha256, size=rec.size, mime=rec.mime,
            )
        )

        # IMAGE artifact (1장)
        img = artifact_store.save_bytes(
            pipeline_id=pid, stage=Stage.IMAGE, kind="image",
            data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, ext=".png", mime="image/png",
        )
        s.add(
            Artifact(
                pipeline_id=pid, stage=Stage.IMAGE, kind="image",
                path=img.rel_path, sha256=img.sha256, size=img.size, mime=img.mime,
            )
        )

        # HUMANIZE artifact (Markdown)
        md = artifact_store.save_text(
            pipeline_id=pid, stage=Stage.HUMANIZE,
            text="# 인간화 본문\n\n안녕하세요...", ext=".md",
        )
        s.add(
            Artifact(
                pipeline_id=pid, stage=Stage.HUMANIZE, kind="text",
                path=md.rel_path, sha256=md.sha256, size=md.size, mime=md.mime,
            )
        )

        s.commit()
    return pid


# ── 성공 케이스 ────────────────────────────────────────────────────────────────


class TestRunPublishSuccess:
    def test_publishes_and_marks_done(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        pid = _setup_pipeline_at_publish(session_factory, artifact_store)
        channel = _success_channel("logno-99")

        result = service.run_publish_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
            channel=channel,
        )

        assert result.success is True
        assert result.next_stage is None  # 마지막 단계
        assert result.next_status == Status.DONE
        assert result.artifact_rel_path is not None
        assert result.artifact_rel_path.endswith(".html")

        with session_factory() as s:
            p = s.get(Pipeline, pid)
            assert Status(p.status) == Status.DONE

    def test_uses_lecture_title_from_topic_artifact(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        pid = _setup_pipeline_at_publish(
            session_factory, artifact_store, position=3
        )
        channel = _success_channel()
        service.run_publish_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
            channel=channel,
        )
        # channel.publish 가 lecture title 로 호출됐는지
        kwargs = channel.publish.call_args.kwargs
        assert "3강" in kwargs["title"]

    def test_publish_result_recorded_as_approval(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        pid = _setup_pipeline_at_publish(session_factory, artifact_store)
        channel = _success_channel("logno-42")
        service.run_publish_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
            channel=channel,
        )
        with session_factory() as s:
            approvals = (
                s.query(Approval)
                .filter(Approval.pipeline_id == pid, Approval.stage == Stage.PUBLISH)
                .all()
            )
            assert len(approvals) == 1
            assert "logno-42" in (approvals[0].note or "")
            assert approvals[0].approver == "channel:naver"

    def test_image_paths_passed_to_channel(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        pid = _setup_pipeline_at_publish(session_factory, artifact_store)
        channel = _success_channel()
        service.run_publish_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
            channel=channel,
        )
        kwargs = channel.publish.call_args.kwargs
        image_paths = kwargs["image_paths"]
        assert len(image_paths) == 1
        # 절대 경로
        assert image_paths[0].is_absolute()


# ── 실패 케이스 ────────────────────────────────────────────────────────────────


class TestRunPublishFailure:
    def test_missing_humanize_artifact_marks_failed(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        with session_factory() as s:
            p = Pipeline(
                series_id=None, position=1, slug="x", idempotency_key="x:1",
                current_stage=Stage.PUBLISH, status=Status.PENDING,
            )
            s.add(p)
            s.commit()
            pid = p.id

        result = service.run_publish_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
            channel=_success_channel(),
        )
        assert result.success is False
        with session_factory() as s:
            p = s.get(Pipeline, pid)
            assert Status(p.status) == Status.FAILED

    def test_channel_failure_marks_pipeline_failed(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        prompt_lib: MagicMock,
    ) -> None:
        pid = _setup_pipeline_at_publish(session_factory, artifact_store)
        channel = MagicMock()
        channel.publish.side_effect = PublishError(
            "naver down", channel="naver", retryable=True
        )

        result = service.run_publish_stage(
            pid,
            llm=_llm_response(),
            prompt_lib=prompt_lib,
            artifact_store=artifact_store,
            channel=channel,
        )
        assert result.success is False
        with session_factory() as s:
            p = s.get(Pipeline, pid)
            assert Status(p.status) == Status.FAILED
