"""NaverChannel — 네이버 블로그 게시 (OAuth 토큰 회전 + Blog API 호출 + 이미지).

흐름:
    1. ``TokenStore.needs_refresh()`` 체크 → 필요하면 ``OAuthClient.refresh()``.
    2. ``image_paths`` 있으면 ``BlogApi(access).upload_photo()`` N회 → URL 매핑.
    3. ``contents_html`` 의 ``<img src="...">`` 의 src 를 네이버 호스팅 URL 로 치환.
    4. ``BlogApi(access).write_post(...)``.
    5. 401 응답 시 강제 refresh 후 1회 재시도 (업로드/게시 양쪽).
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

        access = self._ensure_fresh_access_token()

        # 이미지 업로드 + HTML <img src> 치환
        if image_paths:
            try:
                url_map = self._upload_all(access, image_paths)
            except _AuthRetryNeeded:
                # 업로드 중 401 → 강제 refresh 후 1회 재시도
                access = self._refresh_token(force=True)
                url_map = self._upload_all(access, image_paths, allow_refresh=False)
            contents_html = self._rewrite_image_srcs(contents_html, url_map)

        # 글 게시
        try:
            log_no = BlogApi(access).write_post(
                title=title,
                contents_html=contents_html,
                tags=tags,
            )
        except BlogApiError as e:
            if e.status_code == 401:
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

    # ── 이미지 업로드 ──────────────────────────────────────────────────────

    def _upload_all(
        self,
        access_token: str,
        image_paths: list[Path],
        *,
        allow_refresh: bool = True,
    ) -> dict[str, str]:
        """이미지 N장 순차 업로드 → ``{원본 경로(str): 네이버 URL}`` 매핑 반환.

        401 발생 시 ``allow_refresh`` 면 ``_AuthRetryNeeded`` raise (호출 측이 refresh).
        그 외 실패는 ``PublishError``.
        """
        api = BlogApi(access_token)
        url_map: dict[str, str] = {}
        for path in image_paths:
            try:
                url = api.upload_photo(path)
            except BlogApiError as e:
                if e.status_code == 401 and allow_refresh:
                    raise _AuthRetryNeeded() from e
                raise PublishError(
                    f"image upload failed ({path.name}): {e}",
                    channel=self.name,
                    retryable=e.retryable,
                ) from e
            url_map[str(path)] = url
        return url_map

    @staticmethod
    def _rewrite_image_srcs(html: str, url_map: dict[str, str]) -> str:
        """``<img src="{원본}">`` 의 src 를 네이버 URL 로 치환.

        다양한 경로 표기(forward/backward slash, file://, absolute) 를 모두 시도.
        매칭 실패한 경로는 그대로 — Claude HTML 에서 절대경로 사용을 권장.
        """
        if not url_map:
            return html
        for old_path, new_url in url_map.items():
            old = Path(old_path)
            for variant in {
                old_path,
                str(old),
                old.as_posix(),
                str(old.resolve()) if old.is_absolute() else str(old),
                f"file:///{old.as_posix().lstrip('/')}",
            }:
                if variant and variant in html:
                    html = html.replace(variant, new_url)
        return html

    # ── 토큰 회전 ───────────────────────────────────────────────────────────

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


class _AuthRetryNeeded(Exception):
    """내부 시그널 — 업로드 중 401 발생, 호출 측이 refresh + 재시도해야 함."""
