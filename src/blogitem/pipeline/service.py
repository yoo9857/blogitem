"""파이프라인 도메인 서비스 — Series/Pipeline CRUD + 자동 단계 실행."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from blogitem.pipeline.dto import (
    ArtifactRecord,
    PipelineDTO,
    SeriesDTO,
    StageRunResult,
)
from blogitem.pipeline.models import Artifact, Pipeline, Series
from blogitem.pipeline.stages import Stage, Status
from blogitem.pipeline.state_machine import (
    INITIAL_STATUS,
    InvalidTransitionError,
    assert_transition,
    next_stage,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from blogitem.ai.base import LlmClient
    from blogitem.ai.prompts import PromptLibrary
    from blogitem.pipeline.artifacts import ArtifactStore


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """간단한 슬러그화. 영문/숫자만 보존, 빈 결과 시 'topic' 폴백."""
    s = _SLUG_RE.sub("-", text.lower().strip()).strip("-")
    return s or "topic"


class PipelineService:
    """시리즈/파이프라인 CRUD + 자동 단계 실행 (TOPIC/DRAFT/PUBLISH)."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    # ── 시리즈 / 파이프라인 생성 ─────────────────────────────────────────────

    def create_series_with_pipelines(
        self,
        *,
        topic: str,
        lecture_count: int,
    ) -> SeriesDTO:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic 은 비워둘 수 없습니다")
        if not 1 <= lecture_count <= 100:
            raise ValueError("강의 수는 1~100 사이여야 합니다")

        slug_base = slugify(topic)

        with self._sf() as s:
            series = Series(topic=topic, status="active")
            s.add(series)
            s.flush()

            for i in range(1, lecture_count + 1):
                p = Pipeline(
                    series_id=series.id,
                    position=i,
                    slug=f"{slug_base}-{i:02d}",
                    idempotency_key=f"series:{series.id}:lecture:{i}:v1",
                    current_stage=Stage.TOPIC,
                    status=Status.PENDING,
                )
                s.add(p)

            s.commit()

            return SeriesDTO(
                id=series.id,
                topic=series.topic,
                status=series.status,
                created_at=series.created_at,
                pipeline_count=lecture_count,
            )

    def create_pipeline(
        self,
        *,
        topic: str,
        idempotency_key: str | None = None,
    ) -> PipelineDTO:
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

            return self._to_pipeline_dto(pipeline, series_topic=None)

    # ── 조회 ────────────────────────────────────────────────────────────────

    def list_pipelines(self, *, limit: int = 200) -> list[PipelineDTO]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be 1~1000")

        with self._sf() as s:
            stmt = (
                select(Pipeline, Series.topic)
                .outerjoin(Series, Pipeline.series_id == Series.id)
                .order_by(Pipeline.id.desc())
                .limit(limit)
            )
            return [
                self._to_pipeline_dto(p, series_topic=topic)
                for p, topic in s.execute(stmt).all()
            ]

    def list_series(self) -> list[SeriesDTO]:
        with self._sf() as s:
            stmt = (
                select(Series, func.count(Pipeline.id).label("count"))
                .outerjoin(Pipeline, Pipeline.series_id == Series.id)
                .group_by(Series.id)
                .order_by(Series.id.desc())
            )
            return [
                SeriesDTO(
                    id=series.id,
                    topic=series.topic,
                    status=series.status,
                    created_at=series.created_at,
                    pipeline_count=int(count),
                )
                for series, count in s.execute(stmt).all()
            ]

    def get_pipeline(self, pipeline_id: int) -> PipelineDTO | None:
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
            return self._to_pipeline_dto(p, series_topic=topic)

    # ── 1단계: TOPIC (Claude 자동) ──────────────────────────────────────────

    def run_topic_stage(
        self,
        pipeline_id: int,
        *,
        llm: LlmClient,
        prompt_lib: PromptLibrary,
        artifact_store: ArtifactStore,
        lecture_count: int = 20,
        model: str | None = None,
    ) -> StageRunResult:
        """1단계 — Claude 가 주제·커리큘럼 설계 → JSON 산출물 + IMAGE 단계로 전이.

        흐름:
            1. 검증: TOPIC + PENDING 상태 확인 → RUNNING 전이 (커밋).
            2. LLM 호출 (세션 외부).
            3. 산출물 디스크 저장.
            4. Artifact 레코드 + IMAGE/AWAITING_INPUT 전이 (단일 트랜잭션).

        실패 시 status=FAILED 로 마킹하고 ``StageRunResult(success=False)`` 반환.
        """
        topic_text = self._begin_topic_stage(pipeline_id)

        try:
            system, user = prompt_lib.topic(
                topic=topic_text, lecture_count=lecture_count
            )
            response = llm.complete(system=system, user=user, model=model)
        except Exception as e:  # noqa: BLE001 — 모든 LLM 실패는 FAILED 로
            self._mark_stage_failed(pipeline_id, error=str(e))
            return StageRunResult(
                pipeline_id=pipeline_id,
                stage=Stage.TOPIC,
                success=False,
                artifact_rel_path=None,
                next_stage=None,
                next_status=None,
                error=f"{type(e).__name__}: {e}",
            )

        record = artifact_store.save_text(
            pipeline_id=pipeline_id,
            stage=Stage.TOPIC,
            text=response.text,
            ext=".json",
        )
        self._finish_topic_stage(pipeline_id, record=record)

        return StageRunResult(
            pipeline_id=pipeline_id,
            stage=Stage.TOPIC,
            success=True,
            artifact_rel_path=record.rel_path,
            next_stage=Stage.IMAGE,
            next_status=Status.AWAITING_INPUT,
            error=None,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    # ── private 전이 ────────────────────────────────────────────────────────

    def _begin_topic_stage(self, pipeline_id: int) -> str:
        """TOPIC 시작 — 검증 + RUNNING 전이. 시리즈/파이프라인 주제 텍스트 반환."""
        with self._sf() as s:
            pipeline = s.get(Pipeline, pipeline_id)
            if pipeline is None:
                raise ValueError(f"pipeline {pipeline_id} not found")
            if Stage(pipeline.current_stage) != Stage.TOPIC:
                raise InvalidTransitionError(
                    f"current stage is {pipeline.current_stage}, expected TOPIC"
                )
            assert_transition(Status(pipeline.status), Status.RUNNING)

            if pipeline.series_id:
                series = s.get(Series, pipeline.series_id)
                topic_text = series.topic if series else pipeline.slug
            else:
                topic_text = pipeline.slug

            pipeline.status = Status.RUNNING
            s.commit()
            return topic_text

    def _finish_topic_stage(self, pipeline_id: int, *, record: ArtifactRecord) -> None:
        """TOPIC 성공 — Artifact 저장 + 다음 단계 전이."""
        with self._sf() as s:
            pipeline = s.get(Pipeline, pipeline_id)
            if pipeline is None:
                raise ValueError(f"pipeline {pipeline_id} disappeared")

            s.add(
                Artifact(
                    pipeline_id=pipeline_id,
                    stage=Stage.TOPIC,
                    kind="text",
                    path=record.rel_path,
                    sha256=record.sha256,
                    size=record.size,
                    mime=record.mime,
                )
            )

            nxt = next_stage(Stage.TOPIC)
            if nxt is None:
                pipeline.status = Status.DONE
            else:
                pipeline.current_stage = nxt
                pipeline.status = INITIAL_STATUS[nxt]
            s.commit()

    def _mark_stage_failed(self, pipeline_id: int, *, error: str) -> None:
        with self._sf() as s:
            pipeline = s.get(Pipeline, pipeline_id)
            if pipeline is None:
                return
            pipeline.status = Status.FAILED
            s.commit()

    # ── DTO 변환 ────────────────────────────────────────────────────────────

    @staticmethod
    def _to_pipeline_dto(p: Pipeline, *, series_topic: str | None) -> PipelineDTO:
        return PipelineDTO(
            id=p.id,
            series_id=p.series_id,
            series_topic=series_topic,
            position=p.position,
            slug=p.slug,
            current_stage=Stage(p.current_stage),
            status=Status(p.status),
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
