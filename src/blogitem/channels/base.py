"""PublishChannel Protocol — 미래 채널(티스토리·미디엄) 통합 가능."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PublishResult:
    """채널 게시 결과."""

    def __init__(self, *, channel: str, external_id: str, url: str | None = None) -> None:
        self.channel = channel
        self.external_id = external_id  # 네이버 logNo 등
        self.url = url


class PublishChannel(Protocol):
    """게시 채널 추상화."""

    name: str

    def publish(
        self,
        *,
        title: str,
        contents_html: str,
        image_paths: list[Path],
        tags: list[str] | None = None,
    ) -> PublishResult:
        """게시 실행. 실패 시 ``PublishError`` raise."""
        ...


class PublishError(RuntimeError):
    """채널 게시 실패. ``retryable`` 로 재시도 분기."""

    def __init__(self, message: str, *, channel: str, retryable: bool) -> None:
        super().__init__(message)
        self.channel = channel
        self.retryable = retryable
