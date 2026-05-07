"""Orchestrator — 자동 단계(TOPIC/DRAFT/PUBLISH) 진행 + 다음 단계 전이 트리거.

QTimer 또는 외부 cron 으로 주기적 호출. 한 번 호출에서 처리할 수 있는 파이프라인을
배치로 가져와 처리하고 다음 호출까지 대기.
"""

from __future__ import annotations


class Orchestrator:
    """자동 단계 진행 엔진.

    P3 — 본격 구현. 현재는 인터페이스만.
    """

    def tick(self) -> dict[str, int]:
        """1 사이클 진행.

        Returns:
            ``{advanced: N, retried: N, dead: N, elapsed: sec}``
        """
        raise NotImplementedError("P3 — 구현 필요")
