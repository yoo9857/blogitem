"""파이프라인 도메인 서비스.

UI/CLI 가 ORM 직접 다루지 않도록 격리. DTO 로만 응답.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from blogitem.pipeline.dto import PipelineDTO, SeriesDTO
from blogitem.pipeline.models import Pipeline, Series
from blogitem.pipeline.stages import Stage, Status

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """간단한 슬러그화. 영문/숫자만 보존, 한국어는 보존하지 않으므로 빈 결과 시 'topic' 폴백."""
    s = _SLUG_RE.sub("-", text.lower().strip()).strip("-")
    return s or "topic"


class PipelineService:
    """파이프라인/시리즈 CRUD + 단계 전이 (P3 에서 확장)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    # ── 시리즈 생성 ─────────────────────────────────────────────────────────

    def create_series_with_pipelines(
        self,
        *,
        topic: str,
        lecture_count: int,
    ) -> SeriesDTO:
        """시리즈 + N 파이프라인 생성 (단일 트랜잭션).

        Args:
            topic: 시리즈 주제 (예: "C언어 20강").
            lecture_count: 1~100 — 생성할 파이프라인(=글) 수.

        Raises:
            ValueError: 검증 실패.
        """
        topic = topic.strip()
        if not topic:
            raise ValueError("topic 은 비워둘 수 없습니다")
        if not 1 <= lecture_count <= 100:
            raise ValueError("강의 수는 1~100 사이여야 합니다")

        slug_base = slugify(topic)

        with self._sf() as s:
            series = Series(topic=topic, status="active")
            s.add(series)
            s.flush()  # series.id 확보

            for i in range(1, lecture_count + 1):
                pipeline = Pipeline(
                    series_id=series.id,
                    position=i,
                    slug=f"{slug_base}-{i:02d}",
                    idempotency_key=f"series:{series.id}:lecture:{i}:v1",
                    current_stage=Stage.TOPIC,
                    status=Status.PENDING,
                )
                s.add(pipeline)

            s.commit()

            return SeriesDTO(
                id=series.id,
                topic=series.topic,
                status=series.status,
                created_at=series.created_at,
                pipeline_count=lecture_count,
            )

    # ── 단일 파이프라인 (시리즈 없음) ───────────────────────────────────────

    def create_pipeline(
        self,
        *,
        topic: str,
        idempotency_key: str | None = None,
    ) -> PipelineDTO:
        """시리즈 없는 1회성 파이프라인."""
        topic = topic.strip()
        if not topic:
            raise ValueError("topic 은 비워둘 수 없습니다")
        slug = slugify(topic)
        key = idempotency_key or f"single:{slug}:v1"

        with self._sf() as s:
            pipeline = Pipeline(
                series_id=None,
                position=1,
                slug=slug,
                idempotency_key=key,
                current_stage=Stage.TOPIC,
                status=Status.PENDING,
            )
            s.add(pipeline)
            s.commit()

            return PipelineDTO(
                id=pipeline.id,
                series_id=None,
                series_topic=None,
                position=pipeline.position,
                slug=pipeline.slug,
                current_stage=Stage(pipeline.current_stage),
                status=Status(pipeline.status),
                created_at=pipeline.created_at,
                updated_at=pipeline.updated_at,
            )

    # ── 조회 ────────────────────────────────────────────────────────────────

    def list_pipelines(self, *, limit: int = 200) -> list[PipelineDTO]:
        """최근 파이프라인 목록 (id desc)."""
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be 1~1000")

        with self._sf() as s:
            stmt = (
                select(Pipeline, Series.topic)
                .outerjoin(Series, Pipeline.series_id == Series.id)
                .order_by(Pipeline.id.desc())
                .limit(limit)
            )
            rows = s.execute(stmt).all()
            return [
                PipelineDTO(
                    id=p.id,
                    series_id=p.series_id,
                    series_topic=topic,
                    position=p.position,
                    slug=p.slug,
                    current_stage=Stage(p.current_stage),
                    status=Status(p.status),
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                )
                for p, topic in rows
            ]

    def list_series(self) -> list[SeriesDTO]:
        """시리즈 목록 — 각 시리즈의 파이프라인 수 포함."""
        with self._sf() as s:
            stmt = (
                select(Series, func.count(Pipeline.id).label("count"))
                .outerjoin(Pipeline, Pipeline.series_id == Series.id)
                .group_by(Series.id)
                .order_by(Series.id.desc())
            )
            rows = s.execute(stmt).all()
            return [
                SeriesDTO(
                    id=series.id,
                    topic=series.topic,
                    status=series.status,
                    created_at=series.created_at,
                    pipeline_count=int(count),
                )
                for series, count in rows
            ]

    def get_pipeline(self, pipeline_id: int) -> PipelineDTO | None:
        """단일 파이프라인 조회."""
        with self._sf() as s:
            stmt = (
                select(Pipeline, Series.topic)
                .outerjoin(Series, Pipeline.series_id == Series.id)
                .where(Pipeline.id == pipeline_id)
            )
            row = s.execute(stmt).first()
            if row is None:
                return None
            p, topic = row
            return PipelineDTO(
                id=p.id,
                series_id=p.series_id,
                series_topic=topic,
                position=p.position,
                slug=p.slug,
                current_stage=Stage(p.current_stage),
                status=Status(p.status),
                created_at=p.created_at,
                updated_at=p.updated_at,
            )
