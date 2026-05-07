"""NaverChannel — 네이버 블로그 글쓰기 API 게시.

P1 — OAuth + Blog API 연동 후 본격 구현.
"""

from __future__ import annotations

from pathlib import Path

from blogitem.channels.base import PublishChannel, PublishResult


class NaverChannel(PublishChannel):
    """네이버 블로그 게시 채널."""

    name = "naver"

    def publish(
        self,
        *,
        title: str,
        contents_html: str,
        image_paths: list[Path],
        tags: list[str] | None = None,
    ) -> PublishResult:
        raise NotImplementedError("P1 — Naver OAuth + Blog API 연동 필요")
