"""정체 감지 — IMAGE/HUMANIZE 24h 무진행 / OAuth 토큰 만료 임박.

QTimer 로 1시간 주기 호출. 발견 시 Notifier 로 알림 + DB 기록.
P5 — 본격 구현.
"""

from __future__ import annotations


class StuckPipelineDetector:
    """장기 무진행 파이프라인 감지."""

    def find_stuck(self, *, hours: int = 24) -> list[int]:
        """``hours`` 시간 이상 ``AWAITING_INPUT`` 상태로 머문 pipeline_id 리스트."""
        raise NotImplementedError("P5 — 구현 필요")


class TokenExpiryDetector:
    """OAuth 토큰 만료 임박 감지 (refresh_token 1년)."""

    def days_until_expiry(self) -> int | None:
        """리프레시 토큰 만료까지 남은 일수. None = 토큰 없음."""
        raise NotImplementedError("P5 — 구현 필요")
