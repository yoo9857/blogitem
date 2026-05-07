"""파이프라인 단계(Stage) + 상태(Status) 정의."""

from __future__ import annotations

from enum import StrEnum


class Stage(StrEnum):
    """파이프라인 6단계 — blog.md 흐름 매핑.

    자동(automatic) — blogitem 이 즉시 진행.
    반자동(semi)    — ChatGPT 웹에서 사람이 작업 후 업로드 대기.
    수동(manual)    — 사람 컨펌 게이트.
    """

    TOPIC = "topic"           # 1. Claude — 주제/커리큘럼 (자동)
    IMAGE = "image"           # 2. ChatGPT 웹 → 업로드 (반자동)
    DRAFT = "draft"           # 3. Claude — 초고 작성 (자동)
    HUMANIZE = "humanize"     # 4. ChatGPT 웹 → 업로드 (반자동)
    CONFIRM = "confirm"       # 5. 사람 컨펌 (수동)
    PUBLISH = "publish"       # 6. Claude + 네이버 게시 (자동)


class Status(StrEnum):
    """단계 처리 상태."""

    PENDING = "pending"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"      # IMAGE/HUMANIZE — 업로드 대기
    AWAITING_REVIEW = "awaiting_review"    # CONFIRM — 사람 검수 대기
    DONE = "done"
    REJECTED = "rejected"                  # CONFIRM 거절 — HUMANIZE 부터 재실행
    FAILED = "failed"                      # 재시도 한도 초과 데드레터
    CANCELLED = "cancelled"
