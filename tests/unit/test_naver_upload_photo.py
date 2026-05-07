"""BlogApi.upload_photo + NaverChannel HTML 치환 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import respx
from httpx import Response

from blogitem.channels.naver import NaverChannel
from blogitem.naver.blog_api import (
    UPLOAD_PHOTO_URL,
    WRITE_POST_URL,
    BlogApi,
    BlogApiError,
)


def _make_image(tmp_path: Path, name: str = "img.png") -> Path:
    p = tmp_path / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    return p


# ── BlogApi.upload_photo ──────────────────────────────────────────────────────


class TestUploadPhoto:
    def test_success_returns_url(self, tmp_path: Path) -> None:
        api = BlogApi("AT_x")
        img = _make_image(tmp_path)

        with respx.mock:
            route = respx.post(UPLOAD_PHOTO_URL).mock(
                return_value=Response(
                    200,
                    json={"result": {"url": "https://blogfiles.naver.net/abc.png"}},
                )
            )
            url = api.upload_photo(img)

        assert url == "https://blogfiles.naver.net/abc.png"
        # multipart 헤더 확인
        req = route.calls.last.request
        assert req.headers["authorization"] == "Bearer AT_x"
        assert "multipart/form-data" in req.headers["content-type"]

    def test_array_response_picks_first(self, tmp_path: Path) -> None:
        api = BlogApi("AT_x")
        img = _make_image(tmp_path)
        with respx.mock:
            respx.post(UPLOAD_PHOTO_URL).mock(
                return_value=Response(
                    200,
                    json={
                        "result": [
                            {"url": "https://blogfiles.naver.net/first.png"},
                            {"url": "https://blogfiles.naver.net/second.png"},
                        ]
                    },
                )
            )
            url = api.upload_photo(img)
        assert url == "https://blogfiles.naver.net/first.png"

    def test_unauthorized(self, tmp_path: Path) -> None:
        api = BlogApi("bad")
        img = _make_image(tmp_path)
        with respx.mock:
            respx.post(UPLOAD_PHOTO_URL).mock(return_value=Response(401, text=""))
            with pytest.raises(BlogApiError) as exc:
                api.upload_photo(img)
        assert exc.value.status_code == 401
        assert exc.value.retryable is False

    def test_5xx_retryable(self, tmp_path: Path) -> None:
        api = BlogApi("AT_x")
        img = _make_image(tmp_path)
        with respx.mock:
            respx.post(UPLOAD_PHOTO_URL).mock(return_value=Response(503, text=""))
            with pytest.raises(BlogApiError) as exc:
                api.upload_photo(img)
        assert exc.value.retryable is True

    def test_no_url_in_response(self, tmp_path: Path) -> None:
        api = BlogApi("AT_x")
        img = _make_image(tmp_path)
        with respx.mock:
            respx.post(UPLOAD_PHOTO_URL).mock(
                return_value=Response(200, json={"result": {}})
            )
            with pytest.raises(BlogApiError, match="no url"):
                api.upload_photo(img)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        api = BlogApi("AT_x")
        with pytest.raises(FileNotFoundError):
            api.upload_photo(tmp_path / "nope.png")

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        api = BlogApi("AT_x")
        bad = tmp_path / "doc.pdf"
        bad.write_bytes(b"x")
        with pytest.raises(ValueError, match="extension"):
            api.upload_photo(bad)

    def test_empty_file(self, tmp_path: Path) -> None:
        api = BlogApi("AT_x")
        empty = tmp_path / "empty.png"
        empty.touch()
        with pytest.raises(ValueError, match="empty"):
            api.upload_photo(empty)


# ── NaverChannel publish with images ─────────────────────────────────────────


def _channel_factory(*, dry_run: bool = False) -> NaverChannel:
    from datetime import datetime, timedelta

    oauth = MagicMock()
    oauth.refresh.return_value = {
        "access_token": "AT_new",
        "refresh_token": "RT_new",
        "expires_in": 3600,
    }
    tokens = MagicMock()
    tokens.get_access_token.return_value = "AT_existing"
    tokens.get_refresh_token.return_value = "RT_existing"
    tokens.needs_refresh.return_value = False
    tokens.save_pair = MagicMock()

    return NaverChannel(oauth_client=oauth, token_store=tokens, dry_run=dry_run)


class TestPublishWithImages:
    def test_uploads_each_image_then_posts(self, tmp_path: Path) -> None:
        ch = _channel_factory()
        img_a = _make_image(tmp_path, "a.png")
        img_b = _make_image(tmp_path, "b.png")
        html = (
            f'<p>본문</p><img src="{img_a}" alt="A"><p>...</p>'
            f'<img src="{img_b}" alt="B">'
        )

        with respx.mock:
            upload_route = respx.post(UPLOAD_PHOTO_URL).mock(
                side_effect=[
                    Response(200, json={"result": {"url": "https://naver.com/a"}}),
                    Response(200, json={"result": {"url": "https://naver.com/b"}}),
                ]
            )
            write_route = respx.post(WRITE_POST_URL).mock(
                return_value=Response(200, json={"result": {"logNo": "777"}})
            )

            result = ch.publish(
                title="제목",
                contents_html=html,
                image_paths=[img_a, img_b],
            )

        assert result.external_id == "777"
        assert upload_route.call_count == 2

        # write_post 의 contents 에 네이버 URL 이 들어갔는지 (form-urlencoded 디코드)
        from urllib.parse import parse_qs

        write_body = write_route.calls.last.request.content.decode()
        form = parse_qs(write_body)
        contents = (form.get("contents") or [""])[0]
        assert "https://naver.com/a" in contents
        assert "https://naver.com/b" in contents
        # 원본 path 는 더 이상 본문에 없어야 함
        assert str(img_a) not in contents
        assert str(img_b) not in contents

    def test_no_images_skips_upload(self, tmp_path: Path) -> None:
        ch = _channel_factory()
        with respx.mock:
            upload_route = respx.post(UPLOAD_PHOTO_URL).mock(
                return_value=Response(200, json={"result": {"url": "x"}})
            )
            respx.post(WRITE_POST_URL).mock(
                return_value=Response(200, json={"result": {"logNo": "1"}})
            )
            ch.publish(
                title="t", contents_html="<p>x</p>", image_paths=[]
            )
        assert upload_route.call_count == 0

    def test_upload_401_triggers_refresh_and_retry(self, tmp_path: Path) -> None:
        ch = _channel_factory()
        img = _make_image(tmp_path)
        with respx.mock:
            respx.post(UPLOAD_PHOTO_URL).mock(
                side_effect=[
                    Response(401, text=""),
                    Response(200, json={"result": {"url": "https://x/ok"}}),
                ]
            )
            respx.post(WRITE_POST_URL).mock(
                return_value=Response(200, json={"result": {"logNo": "999"}})
            )
            result = ch.publish(
                title="t",
                contents_html=f'<img src="{img}">',
                image_paths=[img],
            )
        assert result.external_id == "999"
        ch._oauth.refresh.assert_called_once()  # type: ignore[attr-defined]


class TestRewriteImageSrcs:
    def test_replaces_exact_path(self) -> None:
        from pathlib import Path

        from blogitem.channels.naver import NaverChannel

        html = '<img src="C:/blogitem/data/x.png">'
        result = NaverChannel._rewrite_image_srcs(
            html, {"C:/blogitem/data/x.png": "https://n/x"}
        )
        assert "https://n/x" in result
        assert "C:/blogitem/data/x.png" not in result

    def test_handles_multiple(self) -> None:
        from blogitem.channels.naver import NaverChannel

        html = (
            '<img src="C:/x/a.png" alt="A">'
            '<img src="C:/x/b.png" alt="B">'
        )
        result = NaverChannel._rewrite_image_srcs(
            html,
            {"C:/x/a.png": "https://n/a", "C:/x/b.png": "https://n/b"},
        )
        assert "https://n/a" in result and "https://n/b" in result

    def test_empty_map_unchanged(self) -> None:
        from blogitem.channels.naver import NaverChannel

        html = "<p>no images</p>"
        assert NaverChannel._rewrite_image_srcs(html, {}) == html

    def test_unmatched_path_left_alone(self) -> None:
        from blogitem.channels.naver import NaverChannel

        html = '<img src="C:/missing.png">'
        result = NaverChannel._rewrite_image_srcs(
            html, {"C:/different.png": "https://n/x"}
        )
        assert result == html  # 변경 X
