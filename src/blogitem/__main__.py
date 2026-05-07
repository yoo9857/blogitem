"""GUI 진입점.

실행: ``uv run blogitem`` 또는 ``python -m blogitem``.
"""

from __future__ import annotations

import sys


def main() -> int:
    """blogitem 데스크톱 앱을 시작한다.

    Returns:
        프로세스 종료 코드 (0 = 정상).
    """
    from blogitem.app import run

    return run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
