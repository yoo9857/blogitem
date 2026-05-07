"""QApplication 부트스트랩 + 단일 인스턴스 가드 + 메인 윈도우 시작."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def run(argv: Sequence[str]) -> int:
    """blogitem 메인 루프.

    부트스트랩 절차 (구현 예정 — P0):
        1. ``QLockFile`` 로 단일 인스턴스 보장 (큐 워커 중복 실행 방지).
        2. ``Settings`` 로드 + ``configure_logging`` 호출.
        3. SQLAlchemy engine 생성 + Alembic 마이그레이션 헤드 검증.
        4. ``QApplication`` 생성, QSS 스타일 로드, ``MainWindow`` 표시.
        5. 백그라운드 워커(``QThread``) 가동 — Claude/Naver 호출은 스레드 풀.

    Args:
        argv: 프로세스 명령행 인자.

    Returns:
        ``QApplication.exec()`` 종료 코드.
    """
    raise NotImplementedError("P0 — 부트스트랩 구현 필요")
