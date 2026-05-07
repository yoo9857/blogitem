"""structlog 구조화 로깅 (NDJSON) — 콘솔 + 회전 파일 핸들러."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog


def configure_logging(level: str = "info", log_dir: Path | None = None) -> None:
    """structlog + 표준 logging 통합 초기화.

    Args:
        level: ``debug`` | ``info`` | ``warn`` | ``error``.
        log_dir: NDJSON 파일 출력 디렉토리. None 이면 stderr 만. 디렉토리 자동 생성.

    파일은 ``{log_dir}/blogitem.log`` 에 NDJSON 추가, 5MB 단위 회전 (백업 3개).
    GUI 처럼 stdout 이 캡처되지 않는 환경에서도 디버깅 가능.
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

    handlers: list[logging.Handler] = []

    # stderr — GUI 모드에서도 stderr 는 보통 살아있음
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(log_level)
    handlers.append(stderr_handler)

    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / "blogitem.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setLevel(log_level)
            handlers.append(file_handler)
        except OSError as e:
            stderr_handler.handle(
                logging.LogRecord(
                    name="blogitem.log",
                    level=logging.WARNING,
                    pathname=__file__,
                    lineno=0,
                    msg=f"file logging disabled: {e}",
                    args=(),
                    exc_info=None,
                )
            )

    # 기존 핸들러 제거 후 새로 설정 — 재호출 시 중복 방지
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)
    root.setLevel(log_level)


def get_logger(name: str | None = None) -> Any:
    """structlog 로거 획득.

    Args:
        name: 보통 ``__name__`` 사용.
    """
    return structlog.get_logger(name)
