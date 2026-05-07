"""MainWindow — 좌측 파이프라인 목록 / 우측 단계별 상세.

레이아웃:
    +---------------------------+----------------------------------+
    |  Pipelines (PipelineList) |  Detail (PipelineDetail)         |
    |   - C 강의 1단원         |    Stage 1: TOPIC      [done]    |
    |   - C 강의 2단원         |    Stage 2: IMAGE      [upload]  |
    |   ...                    |    Stage 3: DRAFT      [running] |
    |                          |    ...                            |
    +---------------------------+----------------------------------+
    | Status bar: dry_run=ON · queue: 3 pending · token: 89d left  |
    +--------------------------------------------------------------+

P0 — 본격 구현.
"""

from __future__ import annotations


class MainWindow:
    """blogitem 메인 윈도우 (``QMainWindow`` 상속 — P0).

    - 단일 인스턴스 가드(QLockFile)는 ``app.run`` 에서 처리.
    - 메뉴: 새 시리즈 / 설정 / OAuth 연결 / 로그 보기 / 종료.
    - 백그라운드 워커는 별도 ``QThread`` — Signal/Slot 으로 UI 갱신.
    """
