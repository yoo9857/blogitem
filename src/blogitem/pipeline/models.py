"""ORM 도메인 객체 — Series, Pipeline, PipelineStage, Artifact, Approval."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from blogitem.db import Base
from blogitem.pipeline.stages import Stage, Status


class Series(Base):
    """강의/시리즈 — 1 시리즈 = N 파이프라인 (예: "C언어 20강")."""

    __tablename__ = "series"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    outline: Mapped[str | None] = mapped_column(Text, nullable=True)  # Claude 의 커리큘럼 JSON
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    pipelines: Mapped[list[Pipeline]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )


class Pipeline(Base):
    """1 파이프라인 = 1 블로그 글 = 6단계 흐름."""

    __tablename__ = "pipelines"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uk_pipeline_idem"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[int | None] = mapped_column(ForeignKey("series.id"), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=1)  # 시리즈 내 순번
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    current_stage: Mapped[Stage] = mapped_column(String(32), nullable=False, default=Stage.TOPIC)
    status: Mapped[Status] = mapped_column(String(32), nullable=False, default=Status.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )

    series: Mapped[Series | None] = relationship(back_populates="pipelines")
    stages: Mapped[list[PipelineStage]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[Approval]] = relationship(
        back_populates="pipeline", cascade="all, delete-orphan"
    )


class PipelineStage(Base):
    """단계별 진행 기록 — 감사 추적용."""

    __tablename__ = "pipeline_stages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"), nullable=False)
    stage: Mapped[Stage] = mapped_column(String(32), nullable=False)
    status: Mapped[Status] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    pipeline: Mapped[Pipeline] = relationship(back_populates="stages")


class Artifact(Base):
    """단계 산출물 — 텍스트/이미지/json 메타. 실파일은 디스크에 저장.

    ``path`` 는 ``Settings.artifacts_dir`` 기준 상대 경로
    (예: ``2026/05/12/images/abc.png``).
    """

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"), nullable=False)
    stage: Mapped[Stage] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # text | image | json
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    pipeline: Mapped[Pipeline] = relationship(back_populates="artifacts")


class Approval(Base):
    """사람 컨펌 기록 — accept/reject + 사유."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pipeline_id: Mapped[int] = mapped_column(ForeignKey("pipelines.id"), nullable=False)
    stage: Mapped[Stage] = mapped_column(String(32), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)  # accept | reject
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approver: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)

    pipeline: Mapped[Pipeline] = relationship(back_populates="approvals")
