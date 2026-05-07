"""JobStore Protocol — DB 기반 큐 (SQLAlchemy 구현 + 추후 Redis 옵션)."""

from __future__ import annotations

from typing import Protocol


class Job:
    """큐 잡.

    Attributes:
        id: 잡 ID.
        pipeline_id: 연결된 파이프라인.
        kind: ``publish`` | ``advance`` 등.
        payload: 잡 페이로드 (JSON).
        retry_count: 누적 재시도.
    """

    def __init__(
        self,
        *,
        id: int,
        pipeline_id: int,
        kind: str,
        payload: dict[str, object],
        retry_count: int,
    ) -> None:
        self.id = id
        self.pipeline_id = pipeline_id
        self.kind = kind
        self.payload = payload
        self.retry_count = retry_count


class JobStore(Protocol):
    """잡 큐 추상화."""

    def enqueue(
        self,
        *,
        pipeline_id: int,
        kind: str,
        payload: dict[str, object],
        idempotency_key: str | None = None,
    ) -> bool:
        """큐잉. 멱등키 중복 시 False."""
        ...

    def claim(self, batch: int) -> list[Job]:
        """``pending`` 잡을 ``processing`` 으로 전이하며 가져오기 (트랜잭션 + FOR UPDATE)."""
        ...

    def mark_done(self, job_id: int) -> None: ...
    def mark_retry(self, job_id: int, *, backoff_sec: int, error: str) -> None: ...
    def mark_failed(self, job_id: int, *, error: str) -> None: ...


class DbJobStore:
    """SQLAlchemy 기반 ``JobStore`` 구현. P1 에서 본격 구현."""

    # 시그니처는 Protocol 과 일치하지만 실제 동작은 P1 에서 구현.
