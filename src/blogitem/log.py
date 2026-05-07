"""structlog 구조화 로깅 (NDJSON)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import structlog


def configure_logging(level: str = "info", log_dir: Path | None = None) -> None:
    """structlog + 표준 logging 통합 초기화.

    Args:
        level: ``debug`` | ``info`` | ``warn`` | ``error``.
        log_dir: NDJSON 파일 출력 디렉토리. None 이면 콘솔만.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=False)
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=log_level, format="%(message)s")

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        # 회전·NDJSON 파일 핸들러는 P1 에서 추가 (정책 결정 후).


def get_logger(name: str | None = None) -> Any:
    """structlog 로거 획득.

    Args:
        name: 보통 ``__name__`` 사용.
    """
    return structlog.get_logger(name)
