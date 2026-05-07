"""DTO — 도메인 서비스 ↔ UI 사이의 detached 데이터 전달 객체.

ORM 객체를 UI 레이어에 노출하지 않는다 (lazy loading 지뢰 + 세션 의존 회피).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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


@dataclass(frozen=True, slots=True)
class ArtifactSummary:
    """UI 표시용 산출물 메타 + 미리보기.

    DB 메타 + 디스크 절대경로 + (텍스트라면) 첫 N자 미리보기 + (이미지라면)
    None preview_text. UI 가 즉시 카드에 그려넣고, [전체 보기] 클릭 시 viewer 가
    abs_path 로 풀 컨텐츠 로드.
    """

    id: int
    pipeline_id: int
    stage: Stage
    kind: str  # text | image | image_prompts
    rel_path: str
    abs_path: Path
    sha256: str
    size: int
    mime: str | None
    created_at: datetime
    preview_text: str | None  # text/json artifacts: 첫 ~200자, image: None
    is_text_truncated: bool = False  # preview 가 잘렸는지 (전체보기 버튼 노출용)
