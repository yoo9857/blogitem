"""EmailToBlogChannel — 네이버 블로그 메일 발행 우회.

네이버 블로그 글쓰기 API 신규 신청이 거절될 경우의 폴백 경로.
사용자가 블로그 설정에서 발행 메일 주소를 받아 ``naver_publish_email`` 시크릿에 저장하면,
이 채널이 SMTP 로 메일을 보내고 네이버가 받아서 글로 변환.

P6 — 폴백 필요 시 구현.
"""

from __future__ import annotations

from pathlib import Path

from blogitem.channels.base import PublishChannel, PublishResult


class EmailToBlogChannel(PublishChannel):
    """SMTP 기반 폴백 게시 채널."""

    name = "email_to_blog"

    def publish(
        self,
        *,
        title: str,
        contents_html: str,
        image_paths: list[Path],
        tags: list[str] | None = None,
    ) -> PublishResult:
        raise NotImplementedError("P6 — SMTP 메일 발행 구현 필요")
