"""PipelineService.list_artifact_summaries — UI 카드용 산출물 메타 + 미리보기."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import blogitem.pipeline.models  # noqa: F401
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
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    engine.dispose()


@pytest.fixture
def service(session_factory: sessionmaker[Session]) -> PipelineService:
    return PipelineService(session_factory)


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


def _add_pipeline(session_factory: sessionmaker[Session], slug: str = "x") -> int:
    with session_factory() as s:
        p = Pipeline(
            series_id=None,
            position=1,
            slug=slug,
            idempotency_key=slug,
            current_stage=Stage.TOPIC,
            status=Status.PENDING,
        )
        s.add(p)
        s.commit()
        return p.id


def _add_text_artifact(
    session_factory: sessionmaker[Session],
    store: ArtifactStore,
    *,
    pipeline_id: int,
    stage: Stage,
    text: str,
    ext: str = ".md",
    kind: str = "text",
) -> int:
    record = store.save_text(pipeline_id=pipeline_id, stage=stage, text=text, ext=ext)
    with session_factory() as s:
        a = Artifact(
            pipeline_id=pipeline_id,
            stage=stage,
            kind=kind,
            path=record.rel_path,
            sha256=record.sha256,
            size=record.size,
            mime=record.mime,
        )
        s.add(a)
        s.commit()
        return a.id


def _add_image_artifact(
    session_factory: sessionmaker[Session],
    store: ArtifactStore,
    *,
    pipeline_id: int,
    stage: Stage = Stage.IMAGE,
) -> int:
    record = store.save_bytes(
        pipeline_id=pipeline_id,
        stage=stage,
        kind="image",
        data=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        ext=".png",
        mime="image/png",
    )
    with session_factory() as s:
        a = Artifact(
            pipeline_id=pipeline_id,
            stage=stage,
            kind="image",
            path=record.rel_path,
            sha256=record.sha256,
            size=record.size,
            mime=record.mime,
        )
        s.add(a)
        s.commit()
        return a.id


# ── 기본 조회 ──────────────────────────────────────────────────────────────────


class TestListArtifactSummaries:
    def test_empty_pipeline_returns_empty(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        store: ArtifactStore,
    ) -> None:
        pid = _add_pipeline(session_factory)
        result = service.list_artifact_summaries(pid, artifact_store=store)
        assert result == []

    def test_returns_summary_with_path_and_size(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        store: ArtifactStore,
    ) -> None:
        pid = _add_pipeline(session_factory)
        _add_text_artifact(
            session_factory, store, pipeline_id=pid, stage=Stage.DRAFT, text="hello"
        )

        result = service.list_artifact_summaries(pid, artifact_store=store)
        assert len(result) == 1
        s = result[0]
        assert s.stage == Stage.DRAFT
        assert s.kind == "text"
        assert s.size == len("hello")
        assert s.abs_path.is_file()
        assert s.abs_path.is_absolute()

    def test_text_preview_within_limit(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        store: ArtifactStore,
    ) -> None:
        pid = _add_pipeline(session_factory)
        full_text = "한 줄 본문" * 50  # 길이 충분
        _add_text_artifact(
            session_factory, store, pipeline_id=pid, stage=Stage.DRAFT, text=full_text
        )

        result = service.list_artifact_summaries(
            pid, artifact_store=store, preview_chars=50
        )
        assert result[0].preview_text is not None
        assert len(result[0].preview_text) == 50
        assert result[0].is_text_truncated is True

    def test_short_text_not_truncated(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        store: ArtifactStore,
    ) -> None:
        pid = _add_pipeline(session_factory)
        _add_text_artifact(
            session_factory, store, pipeline_id=pid, stage=Stage.DRAFT, text="abc"
        )

        result = service.list_artifact_summaries(
            pid, artifact_store=store, preview_chars=240
        )
        assert result[0].preview_text == "abc"
        assert result[0].is_text_truncated is False

    def test_image_artifact_no_preview_text(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        store: ArtifactStore,
    ) -> None:
        pid = _add_pipeline(session_factory)
        _add_image_artifact(session_factory, store, pipeline_id=pid)

        result = service.list_artifact_summaries(pid, artifact_store=store)
        assert len(result) == 1
        assert result[0].kind == "image"
        assert result[0].preview_text is None

    def test_image_prompts_kind_gets_preview(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        store: ArtifactStore,
    ) -> None:
        pid = _add_pipeline(session_factory)
        prompts_json = json.dumps({"images": [{"role": "thumbnail", "prompt": "x"}]})
        _add_text_artifact(
            session_factory,
            store,
            pipeline_id=pid,
            stage=Stage.IMAGE,
            text=prompts_json,
            ext=".json",
            kind="image_prompts",
        )

        result = service.list_artifact_summaries(pid, artifact_store=store)
        assert len(result) == 1
        assert result[0].kind == "image_prompts"
        assert result[0].preview_text is not None
        assert "thumbnail" in result[0].preview_text

    def test_orders_by_id_ascending(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        store: ArtifactStore,
    ) -> None:
        pid = _add_pipeline(session_factory)
        # 3개 — TOPIC → IMAGE → DRAFT (DB id 순서가 보존되어야 함)
        ids = [
            _add_text_artifact(
                session_factory, store, pipeline_id=pid, stage=Stage.TOPIC,
                text="t1", ext=".json"
            ),
            _add_image_artifact(session_factory, store, pipeline_id=pid),
            _add_text_artifact(
                session_factory, store, pipeline_id=pid, stage=Stage.DRAFT, text="d1"
            ),
        ]

        result = service.list_artifact_summaries(pid, artifact_store=store)
        assert [a.id for a in result] == ids

    def test_other_pipeline_excluded(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        store: ArtifactStore,
    ) -> None:
        pid_a = _add_pipeline(session_factory, slug="a")
        pid_b = _add_pipeline(session_factory, slug="b")
        _add_text_artifact(
            session_factory, store, pipeline_id=pid_a, stage=Stage.DRAFT, text="A"
        )
        _add_text_artifact(
            session_factory, store, pipeline_id=pid_b, stage=Stage.DRAFT, text="B"
        )

        result_a = service.list_artifact_summaries(pid_a, artifact_store=store)
        assert len(result_a) == 1
        assert result_a[0].pipeline_id == pid_a

    def test_disk_read_failure_yields_none_preview(
        self,
        service: PipelineService,
        session_factory: sessionmaker[Session],
        store: ArtifactStore,
    ) -> None:
        pid = _add_pipeline(session_factory)
        artifact_id = _add_text_artifact(
            session_factory, store, pipeline_id=pid, stage=Stage.DRAFT, text="x"
        )

        # 디스크 파일 강제 삭제 → DB 메타는 그대로
        with session_factory() as s:
            artifact = s.get(Artifact, artifact_id)
            assert artifact is not None
            store.absolute_path(artifact.path).unlink()

        result = service.list_artifact_summaries(pid, artifact_store=store)
        assert len(result) == 1
        assert result[0].preview_text is None  # 읽기 실패 → None
