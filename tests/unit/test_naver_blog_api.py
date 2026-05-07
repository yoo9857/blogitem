"""네이버 블로그 API 단위 테스트 (httpx mocking via respx)."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from blogitem.naver.blog_api import WRITE_POST_URL, BlogApi, BlogApiError


@pytest.fixture
def api() -> BlogApi:
    return BlogApi(access_token="AT_test")


class TestConstructor:
    def test_empty_token_rejected(self) -> None:
        with pytest.raises(ValueError):
            BlogApi(access_token="")


class TestWritePost:
    def test_success_returns_log_no(self, api: BlogApi) -> None:
        with respx.mock:
            route = respx.post(WRITE_POST_URL).mock(
                return_value=Response(
                    200,
                    json={
                        "result": {"logNo": "12345678"},
                        "message": {
                            "@type": "response",
                            "result": {"resultCode": "00", "resultMessage": "success"},
                        },
                    },
                )
            )
            log_no = api.write_post(title="hi", contents_html="<p>본문</p>")

        assert log_no == "12345678"

        # 인증 헤더 + Content-Type 검증
        request = route.calls.last.request
        assert request.headers["authorization"] == "Bearer AT_test"
        assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")

    def test_tags_joined_with_comma(self, api: BlogApi) -> None:
        with respx.mock:
            route = respx.post(WRITE_POST_URL).mock(
                return_value=Response(200, json={"result": {"logNo": "1"}})
            )
            api.write_post(
                title="t",
                contents_html="<p>x</p>",
                tags=["a", "b", "c"],
            )
        body = route.calls.last.request.content.decode()
        assert "tags=a%2Cb%2Cc" in body

    def test_category_no_serialized(self, api: BlogApi) -> None:
        with respx.mock:
            route = respx.post(WRITE_POST_URL).mock(
                return_value=Response(200, json={"result": {"logNo": "1"}})
            )
            api.write_post(title="t", contents_html="<p>x</p>", category_no=42)
        body = route.calls.last.request.content.decode()
        assert "categoryNo=42" in body

    def test_unauthorized_not_retryable(self, api: BlogApi) -> None:
        with respx.mock:
            respx.post(WRITE_POST_URL).mock(return_value=Response(401, text=""))
            with pytest.raises(BlogApiError) as exc_info:
                api.write_post(title="t", contents_html="<p>x</p>")
        assert exc_info.value.status_code == 401
        assert exc_info.value.retryable is False

    def test_forbidden_not_retryable(self, api: BlogApi) -> None:
        with respx.mock:
            respx.post(WRITE_POST_URL).mock(return_value=Response(403, text=""))
            with pytest.raises(BlogApiError) as exc_info:
                api.write_post(title="t", contents_html="<p>x</p>")
        assert exc_info.value.status_code == 403
        assert exc_info.value.retryable is False

    def test_rate_limited_retryable(self, api: BlogApi) -> None:
        with respx.mock:
            respx.post(WRITE_POST_URL).mock(return_value=Response(429, text=""))
            with pytest.raises(BlogApiError) as exc_info:
                api.write_post(title="t", contents_html="<p>x</p>")
        assert exc_info.value.retryable is True

    def test_server_error_retryable(self, api: BlogApi) -> None:
        with respx.mock:
            respx.post(WRITE_POST_URL).mock(return_value=Response(503, text="busy"))
            with pytest.raises(BlogApiError) as exc_info:
                api.write_post(title="t", contents_html="<p>x</p>")
        assert exc_info.value.retryable is True

    def test_200_with_no_log_no_treated_as_failure(self, api: BlogApi) -> None:
        with respx.mock:
            respx.post(WRITE_POST_URL).mock(
                return_value=Response(
                    200,
                    json={
                        "result": {},
                        "message": {
                            "result": {
                                "resultCode": "99",
                                "resultMessage": "internal",
                            }
                        },
                    },
                )
            )
            with pytest.raises(BlogApiError, match="99"):
                api.write_post(title="t", contents_html="<p>x</p>")

    def test_empty_title_rejected(self, api: BlogApi) -> None:
        with pytest.raises(ValueError):
            api.write_post(title="", contents_html="<p>x</p>")

    def test_empty_contents_rejected(self, api: BlogApi) -> None:
        with pytest.raises(ValueError):
            api.write_post(title="t", contents_html="")
