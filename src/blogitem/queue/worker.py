"""작업 큐 워커 — 잡 종류별 핸들러 디스패치.

UI 스레드 차단 방지를 위해 ``QThread`` 안에서 실행.
P1 — 본격 구현.
"""

from __future__ import annotations


class Worker:
    """큐 워커 — 1 사이클당 batch 만큼 처리.

    재시도: 지수 백오프 60→120→240→480→960s, 5회 후 dead-letter.
    """

    def run_once(self) -> dict[str, int]:
        """1 사이클 처리.

        Returns:
            ``{posted, retried, dead, elapsed}``.
        """
        raise NotImplementedError("P1 — 구현 필요")
