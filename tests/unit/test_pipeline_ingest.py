"""ingest_image / advance_image / ingest_humanized / confirm_pipeline 단위 테스트."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import blogitem.pipeline.models  # noqa: F401
from blogitem.db import Base
from blogitem.pipeline.artifacts import ArtifactStore
from blogitem.pipeline.models import Approval, Artifact, Pipeline
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


def _make_pipeline_at_stage(
    session_factory: sessionmaker[Session],
    *,
    stage: Stage,
    status: Status,
) -> int:
    with session_factory() as s:
        p = Pipeline(
            series_id=None, position=1, slug="x", idempotency_key=f"x:{stage.value}",
            current_stage=stage, status=status,
        )
        s.add(p)
        s.commit()
        return p.id


def _make_image_file(tmp_path: Path, name: str = "img.png") -> Path:
    path = tmp_path / name
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return path


# ── ingest_image ──────────────────────────────────────────────────────────────


class TestIngestImage:
    def test_saves_artifact_keeps_stage(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        tmp_path: Path,
    ) -> None:
        pid = _make_pipeline_at_stage(
            session_factory, stage=Stage.IMAGE, status=Status.AWAITING_INPUT
        )
        img = _make_image_file(tmp_path)

        record = service.ingest_image(
            pid, source_path=img, artifact_store=artifact_store
        )

        assert record.mime == "image/png"
        with session_factory() as s:
            p = s.get(Pipeline, pid)
            # stage/status 는 그대로 (advance_image 에서 전이)
            assert Stage(p.current_stage) == Stage.IMAGE
            assert Status(p.status) == Status.AWAITING_INPUT
            count = s.query(Artifact).filter_by(pipeline_id=pid).count()
            assert count == 1

    def test_multiple_images_accumulate(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        tmp_path: Path,
    ) -> None:
        pid = _make_pipeline_at_stage(
            session_factory, stage=Stage.IMAGE, status=Status.AWAITING_INPUT
        )
        for i in range(3):
            img = _make_image_file(tmp_path, name=f"img-{i}.png")
            service.ingest_image(pid, source_path=img, artifact_store=artifact_store)

        with session_factory() as s:
            count = s.query(Artifact).filter_by(pipeline_id=pid).count()
            assert count == 3

    def test_wrong_stage_rejected(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        tmp_path: Path,
    ) -> None:
        pid = _make_pipeline_at_stage(
            session_factory, stage=Stage.TOPIC, status=Status.PENDING
        )
        img = _make_image_file(tmp_path)
        with pytest.raises(InvalidTransitionError):
            service.ingest_image(pid, source_path=img, artifact_store=artifact_store)


# ── advance_image ─────────────────────────────────────────────────────────────


class TestAdvanceImage:
    def test_advances_to_draft_pending_when_images_exist(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
        tmp_path: Path,
    ) -> None:
        pid = _make_pipeline_at_stage(
            session_factory, stage=Stage.IMAGE, status=Status.AWAITING_INPUT
        )
        service.ingest_image(
            pid, source_path=_make_image_file(tmp_path), artifact_store=artifact_store
        )

        service.advance_image(pid)

        with session_factory() as s:
            p = s.get(Pipeline, pid)
            assert Stage(p.current_stage) == Stage.DRAFT
            assert Status(p.status) == Status.PENDING

    def test_no_images_blocks_advance(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        pid = _make_pipeline_at_stage(
            session_factory, stage=Stage.IMAGE, status=Status.AWAITING_INPUT
        )
        with pytest.raises(ValueError, match="이미지"):
            service.advance_image(pid)


# ── ingest_humanized ──────────────────────────────────────────────────────────


class TestIngestHumanized:
    def test_advances_to_confirm_awaiting_review(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
    ) -> None:
        pid = _make_pipeline_at_stage(
            session_factory, stage=Stage.HUMANIZE, status=Status.AWAITING_INPUT
        )
        service.ingest_humanized(
            pid, text="# 인간화 본문\n\n...", artifact_store=artifact_store
        )

        with session_factory() as s:
            p = s.get(Pipeline, pid)
            assert Stage(p.current_stage) == Stage.CONFIRM
            assert Status(p.status) == Status.AWAITING_REVIEW
            count = s.query(Artifact).filter_by(
                pipeline_id=pid, stage=Stage.HUMANIZE
            ).count()
            assert count == 1

    def test_empty_text_rejected(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        artifact_store: ArtifactStore,
    ) -> None:
        pid = _make_pipeline_at_stage(
            session_factory, stage=Stage.HUMANIZE, status=Status.AWAITING_INPUT
        )
        with pytest.raises(ValueError):
            service.ingest_humanized(pid, text="   ", artifact_store=artifact_store)


# ── confirm_pipeline ──────────────────────────────────────────────────────────


class TestConfirmPipeline:
    def test_accept_advances_to_publish_pending(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        pid = _make_pipeline_at_stage(
            session_factory, stage=Stage.CONFIRM, status=Status.AWAITING_REVIEW
        )
        service.confirm_pipeline(pid, accept=True, approver="me", note="LGTM")

        with session_factory() as s:
            p = s.get(Pipeline, pid)
            assert Stage(p.current_stage) == Stage.PUBLISH
            assert Status(p.status) == Status.PENDING
            ap = s.query(Approval).filter_by(pipeline_id=pid).one()
            assert ap.decision == "accept"
            assert ap.note == "LGTM"

    def test_reject_returns_to_humanize_awaiting_input(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        pid = _make_pipeline_at_stage(
            session_factory, stage=Stage.CONFIRM, status=Status.AWAITING_REVIEW
        )
        service.confirm_pipeline(
            pid, accept=False, approver="me", note="기계스럽다"
        )

        with session_factory() as s:
            p = s.get(Pipeline, pid)
            assert Stage(p.current_stage) == Stage.HUMANIZE
            assert Status(p.status) == Status.AWAITING_INPUT
            ap = s.query(Approval).filter_by(pipeline_id=pid).one()
            assert ap.decision == "reject"

    def test_wrong_status_rejected(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
    ) -> None:
        pid = _make_pipeline_at_stage(
            session_factory, stage=Stage.CONFIRM, status=Status.PENDING
        )
        with pytest.raises(InvalidTransitionError):
            service.confirm_pipeline(pid, accept=True)
