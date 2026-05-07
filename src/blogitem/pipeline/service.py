"""파이프라인 도메인 서비스 — 전체 파이프라인 라이프사이클.

자동 단계 (Claude 호출):
    · run_topic_stage    — 1단계, 주제·커리큘럼 JSON
    · run_draft_stage    — 3단계, 초고 Markdown
    · run_publish_stage  — 6단계, HTML 변환 + 채널 게시

수동 단계 (사람 입력 ingest):
    · ingest_image       — 2단계, 이미지 업로드 (다중)
    · ingest_humanized   — 4단계, 인간화 본문 업로드
    · advance_image      — 2단계 → 3단계 (이미지 충분 시)
    · confirm_pipeline   — 5단계 컨펌/거절 (REJECTED → HUMANIZE 회귀)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import desc, func, select

from blogitem.pipeline.dto import (
    ArtifactRecord,
    ArtifactSummary,
    PipelineDTO,
    SeriesDTO,
    StageRunResult,
)
from blogitem.pipeline.models import Approval, Artifact, Pipeline, Series
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
    from blogitem.channels.base import PublishChannel
    from blogitem.pipeline.artifacts import ArtifactStore


_SLUG_RE = re.compile(r"[^a-z0-9]+")


class SeriesPromptsAlreadyExistsError(RuntimeError):
    """시리즈 이미지 프롬프트가 이미 생성됨 — force=True 없이는 재생성 차단."""


def slugify(text: str) -> str:
    """간단한 슬러그화. 영문/숫자만 보존, 빈 결과 시 'topic' 폴백."""
    s = _SLUG_RE.sub("-", text.lower().strip()).strip("-")
    return s or "topic"


class PipelineService:
    """파이프라인/시리즈 도메인 서비스."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    # ─────────────────────────────────────────────────────────────────────
    # 시리즈 / 파이프라인 생성 + 조회
    # ─────────────────────────────────────────────────────────────────────

    def create_series_with_pipelines(
        self, *, topic: str, lecture_count: int
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
                s.add(
                    Pipeline(
                        series_id=series.id,
                        position=i,
                        slug=f"{slug_base}-{i:02d}",
                        idempotency_key=f"series:{series.id}:lecture:{i}:v1",
                        current_stage=Stage.TOPIC,
                        status=Status.PENDING,
                    )
                )
            s.commit()

            return SeriesDTO(
                id=series.id,
                topic=series.topic,
                status=series.status,
                created_at=series.created_at,
                pipeline_count=lecture_count,
            )

    def create_pipeline(
        self, *, topic: str, idempotency_key: str | None = None
    ) -> PipelineDTO:
        topic = topic.strip()
        if not topic:
            raise ValueError("topic 은 비워둘 수 없습니다")
        slug = slugify(topic)
        key = idempotency_key or f"single:{slug}:v1"

        with self._sf() as s:
            p = Pipeline(
                series_id=None,
                position=1,
                slug=slug,
                idempotency_key=key,
                current_stage=Stage.TOPIC,
                status=Status.PENDING,
            )
            s.add(p)
            s.commit()
            return self._to_pipeline_dto(p, series_topic=None)

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

    def list_artifact_summaries(
        self,
        pipeline_id: int,
        *,
        artifact_store: ArtifactStore,
        preview_chars: int = 240,
    ) -> list[ArtifactSummary]:
        """파이프라인의 모든 산출물 메타 + 미리보기 (UI 카드용).

        텍스트/JSON 은 첫 ``preview_chars`` 만 디스크에서 읽고 나머지는 잘라냄
        (성능 + 메모리). 이미지는 ``preview_text=None``.
        """
        from blogitem.log import get_logger

        log = get_logger(__name__)
        with self._sf() as s:
            rows = (
                s.execute(
                    select(Artifact)
                    .where(Artifact.pipeline_id == pipeline_id)
                    .order_by(Artifact.id.asc())
                )
                .scalars()
                .all()
            )

        results: list[ArtifactSummary] = []
        for a in rows:
            abs_path = artifact_store.absolute_path(a.path)
            preview_text: str | None = None
            truncated = False
            if a.kind in ("text", "image_prompts"):
                try:
                    full = abs_path.read_text(encoding="utf-8")
                    truncated = len(full) > preview_chars
                    preview_text = full[:preview_chars]
                except (OSError, UnicodeDecodeError) as e:
                    log.warning(
                        "artifact.preview_failed",
                        artifact_id=a.id,
                        err=f"{type(e).__name__}: {e}",
                    )
            results.append(
                ArtifactSummary(
                    id=a.id,
                    pipeline_id=a.pipeline_id,
                    stage=Stage(a.stage),
                    kind=a.kind,
                    rel_path=a.path,
                    abs_path=abs_path,
                    sha256=a.sha256,
                    size=a.size,
                    mime=a.mime,
                    created_at=a.created_at,
                    preview_text=preview_text,
                    is_text_truncated=truncated,
                )
            )
        return results

    def read_latest_text_artifact(
        self,
        pipeline_id: int,
        stage: Stage,
        *,
        artifact_store: ArtifactStore,
    ) -> str | None:
        """``{stage}`` 의 최근 ``kind=text`` 산출물 본문을 디스크에서 읽어 반환.

        UI 가 디스크 트리를 직접 걷지 않도록 격리. DB 메타 → 절대 경로 → ``read_text``.
        """
        with self._sf() as s:
            artifact = self._latest_artifact(s, pipeline_id, stage, "text")
            rel_path = artifact.path if artifact else None

        if rel_path is None:
            return None
        try:
            return artifact_store.absolute_path(rel_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    # ─────────────────────────────────────────────────────────────────────
    # 1단계 — TOPIC (시리즈-레벨 커리큘럼 — 첫 호출만 Claude, 이후 재사용)
    # ─────────────────────────────────────────────────────────────────────

    def run_topic_stage(
        self,
        pipeline_id: int,
        *,
        llm: LlmClient,
        prompt_lib: PromptLibrary,
        artifact_store: ArtifactStore,
        lecture_count: int = 20,
        model: str | None = None,
        on_line: object = None,
    ) -> StageRunResult:
        """시리즈 커리큘럼을 1회만 생성하고 모든 강의 파이프라인이 공유.

        흐름:
            1. 시리즈가 ``outline`` 을 이미 가지고 있으면 → Claude 호출 X.
               기존 outline 을 이 파이프라인의 TOPIC artifact 로 복사 + 다음 단계 전이.
            2. 없으면 Claude 호출 → 응답을 ``Series.outline`` + 이 파이프라인 artifact
               양쪽에 저장 (다음 강의들이 재사용).
            3. 시리즈 없는 단일 파이프라인은 항상 Claude 호출 (공유 대상 없음).
        """
        topic_text = self._begin_auto_stage(pipeline_id, expected=Stage.TOPIC)

        # 시리즈 outline 재사용 가능 여부 검사 (siblings artifact backfill 포함)
        existing_outline = self._existing_series_outline(
            pipeline_id, artifact_store=artifact_store
        )
        if existing_outline is not None:
            # 캐시 히트 — Claude 호출 없이 즉시 산출물 저장
            record = artifact_store.save_text(
                pipeline_id=pipeline_id,
                stage=Stage.TOPIC,
                text=existing_outline,
                ext=".json",
            )
            self._finish_auto_stage(pipeline_id, stage=Stage.TOPIC, record=record)
            return StageRunResult(
                pipeline_id=pipeline_id,
                stage=Stage.TOPIC,
                success=True,
                artifact_rel_path=record.rel_path,
                next_stage=Stage.IMAGE,
                next_status=Status.AWAITING_INPUT,
                error=None,
                input_tokens=0,
                output_tokens=0,
            )

        # 캐시 미스 — Claude 호출
        # 시리즈 파이프라인이면 실제 형제 수를 강의 수로 사용 (사용자가 시리즈 생성 시
        # 정한 값). 시리즈 없는 단일 파이프라인은 호출 인자 그대로.
        effective_count = self._series_lecture_count(pipeline_id) or lecture_count
        try:
            system, user = prompt_lib.topic(
                topic=topic_text, lecture_count=effective_count
            )
            response = llm.complete(
                system=system, user=user, model=model, on_line=on_line
            )
        except Exception as e:
            self._mark_stage_failed(pipeline_id, error=str(e))
            return _failed_result(pipeline_id, Stage.TOPIC, e)

        # Series.outline 에 저장 (있을 때만 — 다음 강의들이 공유)
        self._save_series_outline(pipeline_id, response.text)

        record = artifact_store.save_text(
            pipeline_id=pipeline_id,
            stage=Stage.TOPIC,
            text=response.text,
            ext=".json",
        )
        self._finish_auto_stage(pipeline_id, stage=Stage.TOPIC, record=record)

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

    def _existing_series_outline(
        self,
        pipeline_id: int,
        *,
        artifact_store: ArtifactStore | None = None,
    ) -> str | None:
        """파이프라인이 속한 시리즈의 캐시된 ``outline`` 반환. 없으면 None.

        2 단계 lookup:
            1. ``Series.outline`` (빠른 경로 — 현 버전 코드가 저장한 값).
            2. 형제 파이프라인의 TOPIC text artifact (백필 — P14 이전 데이터).
               찾으면 디스크에서 읽고 ``Series.outline`` 에 저장 (다음엔 빠른 경로).
        """
        with self._sf() as s:
            p = s.get(Pipeline, pipeline_id)
            if p is None or p.series_id is None:
                return None
            series = s.get(Series, p.series_id)
            if series is None:
                return None
            if series.outline:
                return series.outline
            # 폴백 — 형제 파이프라인의 기존 TOPIC artifact 활용 (백필)
            if artifact_store is None:
                return None
            sibling_artifact = s.execute(
                select(Artifact)
                .join(Pipeline, Pipeline.id == Artifact.pipeline_id)
                .where(
                    Pipeline.series_id == p.series_id,
                    Pipeline.id != pipeline_id,
                    Artifact.stage == Stage.TOPIC,
                    Artifact.kind == "text",
                )
                .order_by(Artifact.id.asc())
                .limit(1)
            ).scalar_one_or_none()
            if sibling_artifact is None:
                return None
            sibling_rel_path = sibling_artifact.path

        # 세션 외부에서 디스크 읽기 — IO 가 트랜잭션 잡지 않게
        try:
            text = artifact_store.absolute_path(sibling_rel_path).read_text(
                encoding="utf-8"
            )
        except (OSError, UnicodeDecodeError):
            return None

        # 백필 — 다음번엔 형제 검색 없이 빠른 경로
        self._save_series_outline(pipeline_id, text)
        return text

    def _series_lecture_count(self, pipeline_id: int) -> int | None:
        """파이프라인이 속한 시리즈의 형제 파이프라인 수 = 의도된 강의 수.

        시리즈 없는 단일 파이프라인은 None — 호출자가 기본값 사용.
        """
        with self._sf() as s:
            p = s.get(Pipeline, pipeline_id)
            if p is None or p.series_id is None:
                return None
            count = s.scalar(
                select(func.count(Pipeline.id)).where(
                    Pipeline.series_id == p.series_id
                )
            )
            return int(count) if count else None

    def _save_series_outline(self, pipeline_id: int, outline_text: str) -> None:
        """``Series.outline`` 에 커리큘럼 저장. 시리즈 없는 파이프라인은 무시."""
        with self._sf() as s:
            p = s.get(Pipeline, pipeline_id)
            if p is None or p.series_id is None:
                return
            series = s.get(Series, p.series_id)
            if series is None:
                return
            series.outline = outline_text
            s.commit()

    # ─────────────────────────────────────────────────────────────────────
    # 2단계 보조 — 이미지 프롬프트 생성 (Claude → 사용자 → ChatGPT 웹)
    # ─────────────────────────────────────────────────────────────────────

    def generate_image_prompts(
        self,
        pipeline_id: int,
        *,
        llm: LlmClient,
        prompt_lib: PromptLibrary,
        artifact_store: ArtifactStore,
        body_image_count: int = 3,
        model: str | None = None,
        on_line: object = None,
    ) -> ArtifactRecord:
        """현재 IMAGE 단계 파이프라인에 대해 Claude 가 이미지 프롬프트 N+1개 생성.

        파이프라인 상태 변경 X — 프롬프트는 별도 artifact (kind="image_prompts")
        로 저장. 사용자가 ChatGPT 웹에서 이미지 생성 후 ``ingest_image`` 로 임포트.
        """
        self._assert_stage(pipeline_id, Stage.IMAGE, Status.AWAITING_INPUT)

        # TOPIC 산출물에서 lecture_meta + series 주제 추출
        with self._sf() as s:
            stmt = (
                select(Pipeline, Series.topic)
                .outerjoin(Series, Pipeline.series_id == Series.id)
                .where(Pipeline.id == pipeline_id)
            )
            row = s.execute(stmt).first()
            if row is None:
                raise ValueError(f"pipeline {pipeline_id} not found")
            p, series_topic = row
            position = int(p.position)

            topic_artifact = self._latest_artifact(s, pipeline_id, Stage.TOPIC, "text")
            if topic_artifact is None:
                raise RuntimeError("TOPIC 산출물이 없음 — 1단계 먼저 실행")

        topic_path = artifact_store.absolute_path(topic_artifact.path)
        try:
            curriculum = json.loads(topic_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"커리큘럼 JSON 파싱 실패: {e}") from e

        lectures = curriculum.get("lectures") or []
        idx = position - 1
        if not (0 <= idx < len(lectures)) or not isinstance(lectures[idx], dict):
            raise RuntimeError(
                f"커리큘럼에 position={position} 강의 메타 없음"
            )
        lecture_meta = lectures[idx]

        system, user = prompt_lib.image_prompts(
            lecture_meta=lecture_meta,
            series_topic=str(series_topic) if series_topic else None,
            body_image_count=body_image_count,
        )
        response = llm.complete(
            system=system, user=user, model=model, on_line=on_line
        )

        # JSON artifact 저장 + DB 메타 (kind="image_prompts" — 일반 텍스트와 구분)
        record = artifact_store.save_text(
            pipeline_id=pipeline_id,
            stage=Stage.IMAGE,
            text=response.text,
            ext=".json",
        )
        with self._sf() as s:
            s.add(
                Artifact(
                    pipeline_id=pipeline_id,
                    stage=Stage.IMAGE,
                    kind="image_prompts",
                    path=record.rel_path,
                    sha256=record.sha256,
                    size=record.size,
                    mime="application/json; charset=utf-8",
                )
            )
            s.commit()
        return record

    # ─────────────────────────────────────────────────────────────────────
    # 2단계 보조 — 시리즈 단위 이미지 프롬프트 (썸네일 1 + 강당 본문 1)
    # ─────────────────────────────────────────────────────────────────────

    def generate_series_image_prompts(
        self,
        series_id: int,
        *,
        llm: LlmClient,
        prompt_lib: PromptLibrary,
        artifact_store: ArtifactStore,
        model: str | None = None,
        on_line: object = None,
        force: bool = False,
    ) -> dict[str, object]:
        """시리즈 한 번에 — 시리즈 썸네일 1 + 강당 본문 1 = N+1 프롬프트.

        결과 JSON 은 시리즈 첫 파이프라인(position=1)의 IMAGE 단계 산출물로 저장.
        강의별 매핑은 응답 JSON 의 ``lecture_position`` 필드로 보존.

        Args:
            series_id: 대상 시리즈 ID.
            force: True 면 기존 산출물이 있어도 재생성. 기본 False — 이미 있으면
                ``SeriesPromptsAlreadyExistsError`` 발생.

        Returns:
            저장된 JSON dict (UI 즉시 표시용).

        Raises:
            ValueError: 시리즈/파이프라인/커리큘럼이 없거나 비정상.
            SeriesPromptsAlreadyExistsError: 이미 생성됨 + force=False.
            RuntimeError: 커리큘럼 JSON 파싱 실패.
        """
        # 시리즈 + 첫 파이프라인 + 커리큘럼 수집
        with self._sf() as s:
            series = s.get(Series, series_id)
            if series is None:
                raise ValueError(f"series {series_id} not found")
            series_topic = series.topic
            outline = series.outline

            first_pipeline = s.execute(
                select(Pipeline)
                .where(Pipeline.series_id == series_id)
                .order_by(Pipeline.position.asc())
                .limit(1)
            ).scalar_one_or_none()
            if first_pipeline is None:
                raise ValueError(f"series {series_id} has no pipelines")
            first_pipeline_id = int(first_pipeline.id)

            # 멱등성 — 이미 생성됐으면 차단
            if not force:
                existing = self._latest_artifact(
                    s, first_pipeline_id, Stage.IMAGE, "image_prompts"
                )
                if existing is not None:
                    raise SeriesPromptsAlreadyExistsError(
                        f"시리즈 #{series_id} 이미지 프롬프트가 이미 생성됨 "
                        f"(artifact #{existing.id}). 재생성하려면 force=True."
                    )

            # outline 폴백 — Series.outline 없으면 첫 파이프라인 TOPIC artifact
            if not outline:
                topic_artifact = self._latest_artifact(
                    s, first_pipeline_id, Stage.TOPIC, "text"
                )
                outline_path = topic_artifact.path if topic_artifact else None
            else:
                outline_path = None

        # outline 텍스트 확보
        if outline:
            outline_text = outline
        elif outline_path:
            try:
                outline_text = artifact_store.absolute_path(outline_path).read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeDecodeError) as e:
                raise RuntimeError(f"커리큘럼 파일 읽기 실패: {e}") from e
        else:
            raise RuntimeError(
                "커리큘럼이 없음 — 1단계(TOPIC) 를 먼저 실행하세요."
            )

        try:
            curriculum = json.loads(outline_text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"커리큘럼 JSON 파싱 실패: {e}") from e

        lectures = curriculum.get("lectures") if isinstance(curriculum, dict) else None
        if not isinstance(lectures, list) or not lectures:
            raise RuntimeError("커리큘럼에 lectures 배열이 없음")

        # LLM 호출
        system, user = prompt_lib.series_image_prompts(
            series_topic=series_topic,
            lectures=[lec for lec in lectures if isinstance(lec, dict)],
        )
        response = llm.complete(
            system=system, user=user, model=model, on_line=on_line
        )

        # 첫 파이프라인의 IMAGE 단계 산출물로 저장
        record = artifact_store.save_text(
            pipeline_id=first_pipeline_id,
            stage=Stage.IMAGE,
            text=response.text,
            ext=".json",
        )
        with self._sf() as s:
            s.add(
                Artifact(
                    pipeline_id=first_pipeline_id,
                    stage=Stage.IMAGE,
                    kind="image_prompts",
                    path=record.rel_path,
                    sha256=record.sha256,
                    size=record.size,
                    mime="application/json; charset=utf-8",
                )
            )
            s.commit()

        # 파싱해서 dict 반환 — UI 즉시 표시
        try:
            data = json.loads(response.text)
            return data if isinstance(data, dict) else {"raw": response.text}
        except json.JSONDecodeError:
            return {"raw": response.text}

    def has_series_image_prompts(self, series_id: int) -> bool:
        """시리즈 첫 파이프라인에 이미지 프롬프트 산출물이 이미 있는지."""
        with self._sf() as s:
            first_pipeline = s.execute(
                select(Pipeline)
                .where(Pipeline.series_id == series_id)
                .order_by(Pipeline.position.asc())
                .limit(1)
            ).scalar_one_or_none()
            if first_pipeline is None:
                return False
            existing = self._latest_artifact(
                s, int(first_pipeline.id), Stage.IMAGE, "image_prompts"
            )
            return existing is not None

    def read_series_image_prompts(
        self, series_id: int, *, artifact_store: ArtifactStore
    ) -> dict[str, object] | None:
        """저장된 시리즈 이미지 프롬프트 JSON 을 dict 로 반환. 없으면 None."""
        with self._sf() as s:
            first_pipeline = s.execute(
                select(Pipeline)
                .where(Pipeline.series_id == series_id)
                .order_by(Pipeline.position.asc())
                .limit(1)
            ).scalar_one_or_none()
            if first_pipeline is None:
                return None
            artifact = self._latest_artifact(
                s, int(first_pipeline.id), Stage.IMAGE, "image_prompts"
            )
            rel_path = artifact.path if artifact else None
        if rel_path is None:
            return None
        try:
            text = artifact_store.absolute_path(rel_path).read_text(encoding="utf-8")
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def read_image_prompts(
        self,
        pipeline_id: int,
        *,
        artifact_store: ArtifactStore,
    ) -> dict[str, object] | None:
        """저장된 이미지 프롬프트 JSON 을 dict 로 반환. 없으면 None."""
        with self._sf() as s:
            artifact = self._latest_artifact(
                s, pipeline_id, Stage.IMAGE, "image_prompts"
            )
            rel_path = artifact.path if artifact else None
        if rel_path is None:
            return None
        try:
            text = artifact_store.absolute_path(rel_path).read_text(encoding="utf-8")
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    # ─────────────────────────────────────────────────────────────────────
    # 2단계 — IMAGE (사용자 업로드)
    # ─────────────────────────────────────────────────────────────────────

    def ingest_image(
        self,
        pipeline_id: int,
        *,
        source_path: Path,
        artifact_store: ArtifactStore,
    ) -> ArtifactRecord:
        """사용자가 업로드한 이미지 1장을 IMAGE 단계 산출물로 등록.

        다중 호출 가능 — 한 파이프라인에 N개 이미지. 단계 전이는 별도
        ``advance_image`` 가 트리거.
        """
        self._assert_stage(pipeline_id, Stage.IMAGE, Status.AWAITING_INPUT)

        record = artifact_store.save_image(
            pipeline_id=pipeline_id,
            stage=Stage.IMAGE,
            source_path=source_path,
        )

        with self._sf() as s:
            s.add(
                Artifact(
                    pipeline_id=pipeline_id,
                    stage=Stage.IMAGE,
                    kind="image",
                    path=record.rel_path,
                    sha256=record.sha256,
                    size=record.size,
                    mime=record.mime,
                )
            )
            s.commit()
        return record

    def advance_image(self, pipeline_id: int) -> None:
        """IMAGE → DRAFT 전이. 이미지 1개 이상 업로드되어 있어야 함."""
        with self._sf() as s:
            p = self._fetch_pipeline_or_raise(s, pipeline_id)
            if Stage(p.current_stage) != Stage.IMAGE:
                raise InvalidTransitionError(
                    f"current stage is {p.current_stage}, expected IMAGE"
                )
            if Status(p.status) != Status.AWAITING_INPUT:
                raise InvalidTransitionError(
                    f"current status is {p.status}, expected AWAITING_INPUT"
                )

            count = s.scalar(
                select(func.count(Artifact.id)).where(
                    Artifact.pipeline_id == pipeline_id,
                    Artifact.stage == Stage.IMAGE,
                )
            )
            if not count:
                raise ValueError("이미지를 1개 이상 업로드해야 다음 단계로 진행 가능")

            assert_transition(Status.AWAITING_INPUT, Status.DONE)
            nxt = next_stage(Stage.IMAGE)
            assert nxt is not None
            p.current_stage = nxt
            p.status = INITIAL_STATUS[nxt]
            s.commit()

    # ─────────────────────────────────────────────────────────────────────
    # 3단계 — DRAFT (Claude 자동)
    # ─────────────────────────────────────────────────────────────────────

    def run_draft_stage(
        self,
        pipeline_id: int,
        *,
        llm: LlmClient,
        prompt_lib: PromptLibrary,
        artifact_store: ArtifactStore,
        model: str | None = None,
        on_line: object = None,
    ) -> StageRunResult:
        """3단계 — Claude 가 초고 Markdown 작성. TOPIC 산출물 + 이미지 메타 사용."""
        self._begin_auto_stage(pipeline_id, expected=Stage.DRAFT)

        # 입력 자료 수집 — RUNNING 전이 후 별도 세션에서
        try:
            series_topic, lecture_meta, image_descriptions = self._gather_draft_inputs(
                pipeline_id, artifact_store
            )
        except Exception as e:
            self._mark_stage_failed(pipeline_id, error=str(e))
            return _failed_result(pipeline_id, Stage.DRAFT, e)

        try:
            system, user = prompt_lib.draft(
                series_topic=series_topic,
                lecture_meta=lecture_meta,
                image_descriptions=image_descriptions,
            )
            response = llm.complete(
                system=system, user=user, model=model, on_line=on_line
            )
        except Exception as e:
            self._mark_stage_failed(pipeline_id, error=str(e))
            return _failed_result(pipeline_id, Stage.DRAFT, e)

        record = artifact_store.save_text(
            pipeline_id=pipeline_id,
            stage=Stage.DRAFT,
            text=response.text,
            ext=".md",
        )
        self._finish_auto_stage(pipeline_id, stage=Stage.DRAFT, record=record)

        return StageRunResult(
            pipeline_id=pipeline_id,
            stage=Stage.DRAFT,
            success=True,
            artifact_rel_path=record.rel_path,
            next_stage=Stage.HUMANIZE,
            next_status=Status.AWAITING_INPUT,
            error=None,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 4단계 — HUMANIZE (사용자 업로드)
    # ─────────────────────────────────────────────────────────────────────

    def ingest_humanized(
        self,
        pipeline_id: int,
        *,
        text: str,
        artifact_store: ArtifactStore,
    ) -> ArtifactRecord:
        """ChatGPT 웹에서 인간화한 본문(Markdown 권장)을 4단계 산출물로 등록 + CONFIRM 전이."""
        if not text.strip():
            raise ValueError("본문이 비어있습니다")
        self._assert_stage(pipeline_id, Stage.HUMANIZE, Status.AWAITING_INPUT)

        record = artifact_store.save_text(
            pipeline_id=pipeline_id,
            stage=Stage.HUMANIZE,
            text=text,
            ext=".md",
        )
        with self._sf() as s:
            s.add(
                Artifact(
                    pipeline_id=pipeline_id,
                    stage=Stage.HUMANIZE,
                    kind="text",
                    path=record.rel_path,
                    sha256=record.sha256,
                    size=record.size,
                    mime=record.mime,
                )
            )
            # HUMANIZE 완료 → CONFIRM/AWAITING_REVIEW
            p = s.get(Pipeline, pipeline_id)
            assert p is not None
            nxt = next_stage(Stage.HUMANIZE)
            assert nxt is not None
            p.current_stage = nxt
            p.status = INITIAL_STATUS[nxt]
            s.commit()
        return record

    # ─────────────────────────────────────────────────────────────────────
    # 5단계 — CONFIRM (사람 게이트)
    # ─────────────────────────────────────────────────────────────────────

    def confirm_pipeline(
        self,
        pipeline_id: int,
        *,
        accept: bool,
        approver: str | None = None,
        note: str | None = None,
    ) -> None:
        """5단계 컨펌. accept=True → PUBLISH 진입. False → HUMANIZE/AWAITING_INPUT 회귀."""
        self._assert_stage(pipeline_id, Stage.CONFIRM, Status.AWAITING_REVIEW)

        with self._sf() as s:
            s.add(
                Approval(
                    pipeline_id=pipeline_id,
                    stage=Stage.CONFIRM,
                    decision="accept" if accept else "reject",
                    approver=approver,
                    note=note,
                )
            )
            p = s.get(Pipeline, pipeline_id)
            assert p is not None

            if accept:
                nxt = next_stage(Stage.CONFIRM)
                assert nxt is not None  # PUBLISH
                p.current_stage = nxt
                p.status = INITIAL_STATUS[nxt]
            else:
                # 거절 — HUMANIZE 단계로 돌아가서 재업로드 대기
                p.current_stage = Stage.HUMANIZE
                p.status = Status.AWAITING_INPUT
            s.commit()

    # ─────────────────────────────────────────────────────────────────────
    # 6단계 — PUBLISH (Claude HTML 변환 + 채널 게시)
    # ─────────────────────────────────────────────────────────────────────

    def run_publish_stage(
        self,
        pipeline_id: int,
        *,
        llm: LlmClient,
        prompt_lib: PromptLibrary,
        artifact_store: ArtifactStore,
        channel: PublishChannel,
        model: str | None = None,
        on_line: object = None,
    ) -> StageRunResult:
        """6단계 — HUMANIZE 산출물(MD) → Claude HTML 변환 → 채널 게시 → DONE."""
        self._begin_auto_stage(pipeline_id, expected=Stage.PUBLISH)

        try:
            title, humanized_md, image_paths = self._gather_publish_inputs(
                pipeline_id, artifact_store
            )
        except Exception as e:
            self._mark_stage_failed(pipeline_id, error=str(e))
            return _failed_result(pipeline_id, Stage.PUBLISH, e)

        # HTML 변환
        try:
            sys_p, usr_p = prompt_lib.publish(
                humanized_markdown=humanized_md,
                image_paths=[str(p) for p in image_paths],
            )
            response = llm.complete(
                system=sys_p, user=usr_p, model=model, on_line=on_line
            )
        except Exception as e:
            self._mark_stage_failed(pipeline_id, error=str(e))
            return _failed_result(pipeline_id, Stage.PUBLISH, e)

        html_record = artifact_store.save_text(
            pipeline_id=pipeline_id,
            stage=Stage.PUBLISH,
            text=response.text,
            ext=".html",
        )

        # 채널 게시
        try:
            publish_result = channel.publish(
                title=title,
                contents_html=response.text,
                image_paths=image_paths,
            )
        except Exception as e:
            # HTML artifact 는 이미 저장 — 다시 호출 시 재사용 가능 (멱등성)
            self._mark_stage_failed(pipeline_id, error=str(e))
            return _failed_result(pipeline_id, Stage.PUBLISH, e)

        # DB Artifact + DONE 전이 + 게시 메타 기록
        with self._sf() as s:
            s.add(
                Artifact(
                    pipeline_id=pipeline_id,
                    stage=Stage.PUBLISH,
                    kind="text",
                    path=html_record.rel_path,
                    sha256=html_record.sha256,
                    size=html_record.size,
                    mime=html_record.mime,
                )
            )
            # 게시 결과를 Approval 비슷한 형태로 기록 (별도 테이블 만들기엔 작아서 note 활용)
            s.add(
                Approval(
                    pipeline_id=pipeline_id,
                    stage=Stage.PUBLISH,
                    decision="accept",
                    approver=f"channel:{publish_result.channel}",
                    note=f"external_id={publish_result.external_id}; url={publish_result.url or ''}",
                )
            )
            p = s.get(Pipeline, pipeline_id)
            assert p is not None
            p.status = Status.DONE
            s.commit()

        return StageRunResult(
            pipeline_id=pipeline_id,
            stage=Stage.PUBLISH,
            success=True,
            artifact_rel_path=html_record.rel_path,
            next_stage=None,
            next_status=Status.DONE,
            error=None,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 단계 전이 헬퍼 (private)
    # ─────────────────────────────────────────────────────────────────────

    def _begin_auto_stage(self, pipeline_id: int, *, expected: Stage) -> str:
        """자동 단계 시작 — 검증 + RUNNING 전이. 시리즈 주제 텍스트 반환 (TOPIC 용)."""
        with self._sf() as s:
            p = self._fetch_pipeline_or_raise(s, pipeline_id)
            if Stage(p.current_stage) != expected:
                raise InvalidTransitionError(
                    f"current stage is {p.current_stage}, expected {expected.value}"
                )
            assert_transition(Status(p.status), Status.RUNNING)

            if p.series_id:
                series = s.get(Series, p.series_id)
                topic_text = series.topic if series else p.slug
            else:
                topic_text = p.slug

            p.status = Status.RUNNING
            s.commit()
            return topic_text

    def _finish_auto_stage(
        self, pipeline_id: int, *, stage: Stage, record: ArtifactRecord
    ) -> None:
        """자동 단계 성공 — Artifact 저장 + 다음 단계 전이."""
        with self._sf() as s:
            p = self._fetch_pipeline_or_raise(s, pipeline_id)
            s.add(
                Artifact(
                    pipeline_id=pipeline_id,
                    stage=stage,
                    kind="text",
                    path=record.rel_path,
                    sha256=record.sha256,
                    size=record.size,
                    mime=record.mime,
                )
            )
            nxt = next_stage(stage)
            if nxt is None:
                p.status = Status.DONE
            else:
                p.current_stage = nxt
                p.status = INITIAL_STATUS[nxt]
            s.commit()

    def _mark_stage_failed(self, pipeline_id: int, *, error: str) -> None:
        with self._sf() as s:
            p = s.get(Pipeline, pipeline_id)
            if p is None:
                return
            p.status = Status.FAILED
            s.commit()

    def _assert_stage(self, pipeline_id: int, stage: Stage, status: Status) -> None:
        with self._sf() as s:
            p = self._fetch_pipeline_or_raise(s, pipeline_id)
            if Stage(p.current_stage) != stage:
                raise InvalidTransitionError(
                    f"current stage is {p.current_stage}, expected {stage.value}"
                )
            if Status(p.status) != status:
                raise InvalidTransitionError(
                    f"current status is {p.status}, expected {status.value}"
                )

    @staticmethod
    def _fetch_pipeline_or_raise(s: Session, pipeline_id: int) -> Pipeline:
        p = s.get(Pipeline, pipeline_id)
        if p is None:
            raise ValueError(f"pipeline {pipeline_id} not found")
        return p

    # ─────────────────────────────────────────────────────────────────────
    # 입력 수집 헬퍼
    # ─────────────────────────────────────────────────────────────────────

    def _gather_draft_inputs(
        self,
        pipeline_id: int,
        artifact_store: ArtifactStore,
    ) -> tuple[str, dict[str, object], list[str]]:
        """DRAFT 단계 입력 수집 — 시리즈 주제, 이번 강의 메타, 이미지 설명.

        Returns:
            (series_topic, lecture_meta_dict, image_descriptions)
        """
        with self._sf() as s:
            stmt = (
                select(Pipeline, Series.topic)
                .outerjoin(Series, Pipeline.series_id == Series.id)
                .where(Pipeline.id == pipeline_id)
            )
            row = s.execute(stmt).first()
            if row is None:
                raise ValueError(f"pipeline {pipeline_id} not found")
            p, series_topic = row
            position = int(p.position)

            topic_artifact = self._latest_artifact(s, pipeline_id, Stage.TOPIC, "text")
            if topic_artifact is None:
                raise RuntimeError("TOPIC 산출물(커리큘럼 JSON)이 없음 — 1단계 먼저 실행 필요")

            image_artifacts = (
                s.execute(
                    select(Artifact)
                    .where(
                        Artifact.pipeline_id == pipeline_id,
                        Artifact.stage == Stage.IMAGE,
                        Artifact.kind == "image",
                    )
                    .order_by(Artifact.id.asc())
                )
                .scalars()
                .all()
            )

        # 세션 외부에서 디스크 읽기
        topic_path = artifact_store.absolute_path(topic_artifact.path)
        try:
            curriculum = json.loads(topic_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"커리큘럼 JSON 파싱 실패: {e}") from e

        lectures = curriculum.get("lectures") or []
        # position 은 1-based, 배열은 0-based
        idx = position - 1
        if idx < 0 or idx >= len(lectures):
            raise RuntimeError(
                f"커리큘럼에 position={position} 강의 메타 없음 (총 {len(lectures)}개)"
            )
        lecture_meta = lectures[idx]
        if not isinstance(lecture_meta, dict):
            raise RuntimeError(f"lecture meta 가 객체가 아님: {type(lecture_meta).__name__}")

        # 이미지 파일명을 임시 설명으로 사용 (P4 에서 사용자가 alt-text 입력 가능)
        image_descriptions = [
            f"[이미지] {Path(a.path).name}" for a in image_artifacts
        ]

        return (
            str(series_topic or curriculum.get("series_title", "")),
            lecture_meta,
            image_descriptions,
        )

    def _gather_publish_inputs(
        self,
        pipeline_id: int,
        artifact_store: ArtifactStore,
    ) -> tuple[str, str, list[Path]]:
        """PUBLISH 단계 입력 — title, humanized markdown, 절대 이미지 경로 리스트."""
        with self._sf() as s:
            p = self._fetch_pipeline_or_raise(s, pipeline_id)
            position = int(p.position)

            humanize_artifact = self._latest_artifact(s, pipeline_id, Stage.HUMANIZE, "text")
            if humanize_artifact is None:
                raise RuntimeError("HUMANIZE 산출물(인간화 본문)이 없음")

            topic_artifact = self._latest_artifact(s, pipeline_id, Stage.TOPIC, "text")
            if topic_artifact is None:
                raise RuntimeError("TOPIC 산출물이 없음 — title 추출 불가")

            image_artifacts = (
                s.execute(
                    select(Artifact)
                    .where(
                        Artifact.pipeline_id == pipeline_id,
                        Artifact.stage == Stage.IMAGE,
                    )
                    .order_by(Artifact.id.asc())
                )
                .scalars()
                .all()
            )
            image_paths = [
                artifact_store.absolute_path(a.path) for a in image_artifacts
            ]

        humanized_md = (
            artifact_store.absolute_path(humanize_artifact.path)
            .read_text(encoding="utf-8")
        )

        topic_text = (
            artifact_store.absolute_path(topic_artifact.path)
            .read_text(encoding="utf-8")
        )
        try:
            curriculum = json.loads(topic_text)
            lectures = curriculum.get("lectures") or []
            idx = position - 1
            title = lectures[idx].get("title") if 0 <= idx < len(lectures) else None
        except (json.JSONDecodeError, AttributeError, TypeError):
            title = None

        if not title:
            # 폴백 — 슬러그
            with self._sf() as s:
                p = self._fetch_pipeline_or_raise(s, pipeline_id)
                title = p.slug

        return title, humanized_md, image_paths

    @staticmethod
    def _latest_artifact(
        s: Session, pipeline_id: int, stage: Stage, kind: str
    ) -> Artifact | None:
        return s.execute(
            select(Artifact)
            .where(
                Artifact.pipeline_id == pipeline_id,
                Artifact.stage == stage,
                Artifact.kind == kind,
            )
            .order_by(desc(Artifact.id))
            .limit(1)
        ).scalar_one_or_none()

    # ─────────────────────────────────────────────────────────────────────
    # DTO 변환
    # ─────────────────────────────────────────────────────────────────────

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


# ── 결과 빌더 ──────────────────────────────────────────────────────────────────


def _failed_result(pipeline_id: int, stage: Stage, error: BaseException) -> StageRunResult:
    return StageRunResult(
        pipeline_id=pipeline_id,
        stage=stage,
        success=False,
        artifact_rel_path=None,
        next_stage=None,
        next_status=None,
        error=f"{type(error).__name__}: {error}",
    )
