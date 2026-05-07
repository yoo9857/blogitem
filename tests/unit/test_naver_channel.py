"""NaverChannel — 토큰 회전 + 401 재시도 흐름 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import respx
from httpx import Response

from blogitem.channels.base import PublishError
from blogitem.channels.naver import NaverChannel
from blogitem.naver.blog_api import WRITE_POST_URL
from blogitem.naver.oauth import TOKEN_URL


def _make_token_store(
    *,
    access_token: str | None = "AT_existing",
    refresh_token: str | None = "RT_existing",
    expires_at: datetime | None = None,
) -> MagicMock:
    """``TokenStore`` 동작을 흉내내는 mock."""
    if expires_at is None:
        expires_at = datetime.now() + timedelta(hours=1)
    ts = MagicMock()
    ts.get_access_token.return_value = access_token
    ts.get_refresh_token.return_value = refresh_token
    ts.needs_refresh.return_value = expires_at <= datetime.now() + timedelta(seconds=60)
    ts.save_pair = MagicMock()
    ts.clear = MagicMock()
    return ts


def _make_oauth_client() -> MagicMock:
    oauth = MagicMock()
    oauth.refresh.return_value = {
        "access_token": "AT_new",
        "refresh_token": "RT_new",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    return oauth


class TestDryRun:
    def test_dry_run_skips_api_call(self) -> None:
        ch = NaverChannel(
            oauth_client=_make_oauth_client(),
            token_store=_make_token_store(),
            dry_run=True,
        )
        with respx.mock:
            # 호출 없음을 보장 — 모킹 안 해도 dry_run 이라 호출 X
            result = ch.publish(
                title="t",
                contents_html="<p>x</p>",
                image_paths=[],
            )
        assert result.channel == "naver"
        assert result.external_id.startswith("dry-")


class TestPublishFlow:
    def test_publish_uses_existing_access_token(self) -> None:
        oauth = _make_oauth_client()
        tokens = _make_token_store(
            access_token="AT_existing",
            expires_at=datetime.now() + timedelta(hours=1),
        )
        ch = NaverChannel(oauth_client=oauth, token_store=tokens)

        with respx.mock:
            route = respx.post(WRITE_POST_URL).mock(
                return_value=Response(200, json={"result": {"logNo": "999"}})
            )
            result = ch.publish(
                title="t", contents_html="<p>x</p>", image_paths=[]
            )

        assert result.external_id == "999"
        assert route.calls.last.request.headers["authorization"] == "Bearer AT_existing"
        oauth.refresh.assert_not_called()

    def test_publish_refreshes_when_expired(self) -> None:
        oauth = _make_oauth_client()
        tokens = _make_token_store(
            access_token="AT_old",
            expires_at=datetime.now() - timedelta(seconds=10),
        )
        ch = NaverChannel(oauth_client=oauth, token_store=tokens)

        with respx.mock:
            route = respx.post(WRITE_POST_URL).mock(
                return_value=Response(200, json={"result": {"logNo": "777"}})
            )
            ch.publish(title="t", contents_html="<p>x</p>", image_paths=[])

        oauth.refresh.assert_called_once_with("RT_existing")
        tokens.save_pair.assert_called_once()
        assert route.calls.last.request.headers["authorization"] == "Bearer AT_new"

    def test_publish_retries_on_401(self) -> None:
        oauth = _make_oauth_client()
        tokens = _make_token_store(
            access_token="AT_stale",
            expires_at=datetime.now() + timedelta(hours=1),  # 만료 안 됐다고 판단했는데
        )
        ch = NaverChannel(oauth_client=oauth, token_store=tokens)

        with respx.mock:
            route = respx.post(WRITE_POST_URL).mock(
                side_effect=[
                    Response(401, text=""),  # 1차: 만료됨
                    Response(200, json={"result": {"logNo": "555"}}),  # 2차: 성공
                ]
            )
            result = ch.publish(title="t", contents_html="<p>x</p>", image_paths=[])

        assert result.external_id == "555"
        assert route.call_count == 2
        oauth.refresh.assert_called_once()  # 강제 리프레시

    def test_publish_no_refresh_token_raises(self) -> None:
        oauth = _make_oauth_client()
        tokens = _make_token_store(refresh_token=None)
        tokens.needs_refresh.return_value = True
        ch = NaverChannel(oauth_client=oauth, token_store=tokens)

        with pytest.raises(PublishError, match="refresh_token"):
            ch.publish(title="t", contents_html="<p>x</p>", image_paths=[])

    def test_publish_5xx_raises_retryable(self) -> None:
        ch = NaverChannel(
            oauth_client=_make_oauth_client(),
            token_store=_make_token_store(),
        )
        with respx.mock:
            respx.post(WRITE_POST_URL).mock(return_value=Response(503, text=""))
            with pytest.raises(PublishError) as exc_info:
                ch.publish(title="t", contents_html="<p>x</p>", image_paths=[])
        assert exc_info.value.retryable is True

    def test_image_paths_warned_but_ignored(self) -> None:
        """P3 미구현 — 이미지 첨부 요청해도 텍스트만 게시."""
        ch = NaverChannel(
            oauth_client=_make_oauth_client(),
            token_store=_make_token_store(),
        )
        with respx.mock:
            respx.post(WRITE_POST_URL).mock(
                return_value=Response(200, json={"result": {"logNo": "1"}})
            )
            result = ch.publish(
                title="t",
                contents_html="<p>x</p>",
                image_paths=[Path("nonexistent.png")],
            )
        assert result.external_id == "1"
