"""NaverChannel — 네이버 블로그 게시 (OAuth 토큰 회전 + Blog API 호출).

흐름:
    1. ``TokenStore.needs_refresh()`` 체크 → 필요하면 ``OAuthClient.refresh()``.
    2. ``BlogApi(access).write_post(...)``.
    3. 401 응답 시 강제 refresh 후 1회 재시도.

이미지 첨부: P3 — ``uploadPhoto.json`` 호출 후 HTML 에 ``<img>`` 임베드.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from blogitem.channels.base import PublishChannel, PublishError, PublishResult
from blogitem.naver.blog_api import BlogApi, BlogApiError

if TYPE_CHECKING:
    from blogitem.naver.oauth import OAuthClient
    from blogitem.naver.token_store import TokenStore


class NaverChannel(PublishChannel):
    """네이버 블로그 게시 채널."""

    name = "naver"

    def __init__(
        self,
        *,
        oauth_client: OAuthClient,
        token_store: TokenStore,
        dry_run: bool = False,
    ) -> None:
        self._oauth = oauth_client
        self._tokens = token_store
        self._dry_run = dry_run

    def publish(
        self,
        *,
        title: str,
        contents_html: str,
        image_paths: list[Path],
        tags: list[str] | None = None,
    ) -> PublishResult:
        if self._dry_run:
            return PublishResult(
                channel=self.name,
                external_id=f"dry-{uuid4().hex[:12]}",
            )

        if image_paths:
            # P3 — uploadPhoto.json 으로 업로드 후 HTML 에 <img> 임베드.
            from blogitem.log import get_logger

            get_logger(__name__).warning(
                "naver.images_not_yet_attached",
                count=len(image_paths),
                stage="P3 미구현",
            )

        access = self._ensure_fresh_access_token()

        try:
            log_no = BlogApi(access).write_post(
                title=title,
                contents_html=contents_html,
                tags=tags,
            )
        except BlogApiError as e:
            if e.status_code == 401:
                # access_token 이 일찍 만료됐을 수 있음 → 강제 refresh 후 1회 재시도
                access = self._refresh_token(force=True)
                try:
                    log_no = BlogApi(access).write_post(
                        title=title,
                        contents_html=contents_html,
                        tags=tags,
                    )
                except BlogApiError as e2:
                    raise PublishError(
                        str(e2), channel=self.name, retryable=e2.retryable
                    ) from e2
            else:
                raise PublishError(
                    str(e), channel=self.name, retryable=e.retryable
                ) from e

        return PublishResult(channel=self.name, external_id=log_no)

    # ── 토큰 회전 ───────────────────────────────────────────────────────────

    def _ensure_fresh_access_token(self) -> str:
        if self._tokens.needs_refresh():
            return self._refresh_token()
        access = self._tokens.get_access_token()
        if access is None:
            return self._refresh_token()
        return access

    def _refresh_token(self, *, force: bool = False) -> str:
        """refresh_token 으로 access_token 갱신.

        Naver 는 refresh 시 refresh_token 이 회전될 수 있으므로 응답 결과를
        그대로 ``TokenStore.save_pair`` 한다. 회전 안 됐으면 기존값 유지.
        """
        rt = self._tokens.get_refresh_token()
        if not rt:
            raise PublishError(
                "no refresh_token — 재인증 필요 (설정 → 네이버 연결)",
                channel=self.name,
                retryable=False,
            )
        try:
            result = self._oauth.refresh(rt)
        except Exception as e:  # noqa: BLE001 — OAuth 모듈 예외 포함 모두 실패로 묶음
            raise PublishError(
                f"token refresh 실패: {type(e).__name__}",
                channel=self.name,
                retryable=False,
            ) from e

        access = str(result["access_token"])
        new_rt = str(result.get("refresh_token") or "")
        self._tokens.save_pair(
            access_token=access,
            refresh_token=new_rt or rt,  # 회전 안 됐으면 기존값 유지
            expires_in=int(result.get("expires_in") or 3600),
        )
        return access
