"""Watchdog — 정체된 파이프라인 + OAuth 토큰 만료 감지.

설계:
    · ``StuckPipelineDetector`` — DB 쿼리만, side-effect 없음.
    · ``TokenExpiryDetector`` — TokenStore 에서 refresh_token 발급 시각 조회.
    · ``WatchdogService`` (QObject) — QTimer 로 주기 호출, 시그널로 결과 통지.

UI 가 직접 폴링하지 않고 시그널을 구독하는 패턴 — 테스트 + 책임 분리에 유리.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from blogitem.pipeline.models import Pipeline
from blogitem.pipeline.stages import Stage, Status

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from blogitem.naver.token_store import TokenStore


@dataclass(frozen=True, slots=True)
class StuckPipeline:
    """정체된 파이프라인 메타."""

    id: int
    slug: str
    stage: Stage
    status: Status
    idle_hours: float


# ── Stuck Pipeline Detector ────────────────────────────────────────────────────


class StuckPipelineDetector:
    """장기 무진행 파이프라인 감지.

    감지 대상:
        - AWAITING_INPUT  — 사람이 업로드 안 한 채 N시간 경과 (IMAGE/HUMANIZE)
        - AWAITING_REVIEW — 사람이 컨펌 안 한 채 N시간 경과 (CONFIRM)
        - FAILED          — 어떤 시점이든 실패 상태로 남아있음 (시간 무관)
    """

    _STUCK_STATUSES = (Status.AWAITING_INPUT, Status.AWAITING_REVIEW)

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._sf = session_factory

    def find_stuck(self, *, hours: int = 24) -> list[StuckPipeline]:
        """``hours`` 시간 이상 정체된 파이프라인 목록.

        FAILED 는 시간 무관 항상 포함.
        """
        if hours < 0:
            raise ValueError("hours must be non-negative")

        cutoff = datetime.now() - timedelta(hours=hours)
        with self._sf() as s:
            stmt = (
                select(Pipeline)
                .where(
                    (
                        (Pipeline.status.in_([s.value for s in self._STUCK_STATUSES]))
                        & (Pipeline.updated_at < cutoff)
                    )
                    | (Pipeline.status == Status.FAILED.value)
                )
                .order_by(Pipeline.updated_at.asc())
            )
            rows = s.execute(stmt).scalars().all()
            now = datetime.now()
            return [
                StuckPipeline(
                    id=p.id,
                    slug=p.slug,
                    stage=Stage(p.current_stage),
                    status=Status(p.status),
                    idle_hours=(now - p.updated_at).total_seconds() / 3600.0,
                )
                for p in rows
            ]


# ── Token Expiry Detector ──────────────────────────────────────────────────────


class TokenExpiryDetector:
    """OAuth refresh_token 만료 임박 감지."""

    def __init__(self, token_store: TokenStore) -> None:
        self._tokens = token_store

    def days_until_expiry(self) -> int | None:
        """refresh_token 만료까지 남은 일수. None = 미발급."""
        return self._tokens.days_until_refresh_expiry()

    def is_expiring_soon(self, *, threshold_days: int = 30) -> bool:
        """``threshold_days`` 일 이내 만료면 True. 미발급 시 False."""
        days = self.days_until_expiry()
        if days is None:
            return False
        return days <= threshold_days


# ── Watchdog 서비스 (QObject) ─────────────────────────────────────────────────


def make_watchdog_service(
    *,
    session_factory: sessionmaker[Session],
    token_store: TokenStore,
    parent: object | None = None,
) -> object:
    """``WatchdogService`` 팩토리.

    PySide6 import 를 헤드리스 환경에서도 모듈 import 자체는 가능하게
    함수로 격리. 실제 ``QObject`` 상속 클래스는 함수 내부에서 정의.
    """
    from PySide6.QtCore import QObject, QTimer, Signal

    class WatchdogService(QObject):
        """주기적 모니터링 — Stuck + Token + 큐 카운트.

        Signals:
            stuck_found(list)    — list[StuckPipeline]
            token_expiring(int)   — 남은 일수 (≤ threshold 일 때만)
            queue_summary(dict)   — {pending, awaiting_input, awaiting_review, failed, done}
        """

        stuck_found = Signal(list)
        token_expiring = Signal(int)
        queue_summary = Signal(dict)

        def __init__(self) -> None:
            super().__init__(parent)  # type: ignore[arg-type]
            self._stuck = StuckPipelineDetector(session_factory)
            self._token = TokenExpiryDetector(token_store)
            self._sf = session_factory
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.tick)

        def start(self, *, interval_min: int = 60) -> None:
            if interval_min < 1:
                raise ValueError("interval_min must be >= 1")
            self._timer.start(interval_min * 60 * 1000)
            self.tick()

        def stop(self) -> None:
            self._timer.stop()

        def tick(self) -> None:
            from blogitem.log import get_logger

            log = get_logger(__name__)

            try:
                stuck = self._stuck.find_stuck(hours=24)
                if stuck:
                    self.stuck_found.emit(stuck)
            except Exception as e:  # noqa: BLE001
                log.warning("watchdog.stuck_failed", err=f"{type(e).__name__}: {e}")

            try:
                if self._token.is_expiring_soon(threshold_days=30):
                    days = self._token.days_until_expiry()
                    if days is not None:
                        self.token_expiring.emit(days)
            except Exception as e:  # noqa: BLE001
                log.warning("watchdog.token_failed", err=f"{type(e).__name__}: {e}")

            try:
                self.queue_summary.emit(self._compute_queue_summary())
            except Exception as e:  # noqa: BLE001
                log.warning("watchdog.queue_failed", err=f"{type(e).__name__}: {e}")

        def _compute_queue_summary(self) -> dict[str, int]:
            from sqlalchemy import func

            with self._sf() as s:
                stmt = select(Pipeline.status, func.count(Pipeline.id)).group_by(
                    Pipeline.status
                )
                counts = {status: int(n) for status, n in s.execute(stmt).all()}

            # Status enum 모든 값에 대해 0 으로 초기화 후 채움
            return {st.value: counts.get(st.value, 0) for st in Status}

    return WatchdogService()
