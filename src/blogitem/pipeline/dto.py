"""DTO — 도메인 서비스 ↔ UI 사이의 detached 데이터 전달 객체.

ORM 객체를 UI 레이어에 노출하지 않는다 (lazy loading 지뢰 + 세션 의존 회피).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from blogitem.pipeline.stages import Stage, Status


@dataclass(frozen=True, slots=True)
class SeriesDTO:
    """강의/시리즈."""

    id: int
    topic: str
    status: str
    created_at: datetime
    pipeline_count: int


@dataclass(frozen=True, slots=True)
class PipelineDTO:
    """1 블로그 글 = 1 파이프라인."""

    id: int
    series_id: int | None
    series_topic: str | None
    position: int
    slug: str
    current_stage: Stage
    status: Status
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """``ArtifactStore.save_*`` 가 반환하는 파일 메타.

    Service 가 이걸 받아 ``Artifact`` ORM row 로 변환.
    """

    rel_path: str
    sha256: str
    size: int
    mime: str | None


@dataclass(frozen=True, slots=True)
class StageRunResult:
    """자동 단계 실행 결과 — UI 알림용."""

    pipeline_id: int
    stage: Stage
    success: bool
    artifact_rel_path: str | None
    next_stage: Stage | None
    next_status: Status | None
    error: str | None
    input_tokens: int = 0
    output_tokens: int = 0
