"""네이버 OAuth 클라이언트 단위 테스트 (httpx mocking via respx)."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from blogitem.naver.oauth import (
    AUTHORIZE_URL,
    TOKEN_URL,
    OAuthClient,
    OAuthError,
    build_state,
)


@pytest.fixture
def client() -> OAuthClient:
    return OAuthClient(
        client_id="cid",
        client_secret="csec",
        redirect_uri="http://127.0.0.1:8765/naver-callback",
    )


class TestBuildState:
    def test_returns_url_safe_string(self) -> None:
        s = build_state()
        assert len(s) >= 32  # token_urlsafe(32) ≈ 43 chars
        assert "/" not in s and "+" not in s

    def test_returns_unique_each_call(self) -> None:
        assert build_state() != build_state()


class TestAuthorizeUrl:
    def test_includes_required_params(self, client: OAuthClient) -> None:
        url = client.build_authorize_url(state="abc123")
        assert url.startswith(AUTHORIZE_URL)
        assert "response_type=code" in url
        assert "client_id=cid" in url
        assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8765%2Fnaver-callback" in url
        assert "state=abc123" in url

    def test_empty_state_rejected(self, client: OAuthClient) -> None:
        with pytest.raises(ValueError, match="state required"):
            client.build_authorize_url(state="")


class TestExchangeCode:
    def test_success_returns_normalized_tokens(self, client: OAuthClient) -> None:
        with respx.mock:
            respx.post(TOKEN_URL).mock(
                return_value=Response(
                    200,
                    json={
                        "access_token": "AT",
                        "refresh_token": "RT",
                        "token_type": "Bearer",
                        "expires_in": "3600",
                    },
                )
            )
            result = client.exchange_code("code123", "state456")

        assert result == {
            "access_token": "AT",
            "refresh_token": "RT",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    def test_naver_error_response_raises(self, client: OAuthClient) -> None:
        with respx.mock:
            respx.post(TOKEN_URL).mock(
                return_value=Response(
                    200,
                    json={"error": "invalid_grant", "error_description": "bad code"},
                )
            )
            with pytest.raises(OAuthError, match="invalid_grant"):
                client.exchange_code("bad", "state")

    def test_5xx_marked_retryable(self, client: OAuthClient) -> None:
        with respx.mock:
            respx.post(TOKEN_URL).mock(return_value=Response(503, json={}))
            with pytest.raises(OAuthError) as exc_info:
                client.exchange_code("c", "s")
            assert exc_info.value.retryable is True
            assert exc_info.value.status_code == 503

    def test_4xx_not_retryable(self, client: OAuthClient) -> None:
        with respx.mock:
            respx.post(TOKEN_URL).mock(return_value=Response(400, json={}))
            with pytest.raises(OAuthError) as exc_info:
                client.exchange_code("c", "s")
            assert exc_info.value.retryable is False
            assert exc_info.value.status_code == 400

    def test_empty_code_or_state_rejected(self, client: OAuthClient) -> None:
        with pytest.raises(ValueError):
            client.exchange_code("", "state")
        with pytest.raises(ValueError):
            client.exchange_code("code", "")


class TestRefresh:
    def test_success(self, client: OAuthClient) -> None:
        with respx.mock:
            respx.post(TOKEN_URL).mock(
                return_value=Response(
                    200,
                    json={
                        "access_token": "AT_NEW",
                        "refresh_token": "RT_NEW",
                        "expires_in": "3600",
                    },
                )
            )
            result = client.refresh("RT_OLD")
        assert result["access_token"] == "AT_NEW"
        assert result["refresh_token"] == "RT_NEW"

    def test_empty_refresh_token_rejected(self, client: OAuthClient) -> None:
        with pytest.raises(ValueError):
            client.refresh("")

    def test_naver_error_with_long_description_truncated(self, client: OAuthClient) -> None:
        """긴 error_description 도 메시지가 안전하게 처리되는지."""
        with respx.mock:
            respx.post(TOKEN_URL).mock(
                return_value=Response(
                    200,
                    json={
                        "error": "x",
                        "error_description": "y" * 1000,
                    },
                )
            )
            with pytest.raises(OAuthError) as exc_info:
                client.refresh("rt")
        # 200자 제한 + ":" 포함 → 1000자 그대로 들어가지 않음
        assert len(str(exc_info.value)) < 500


class TestConstructor:
    def test_empty_client_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            OAuthClient(client_id="", client_secret="x", redirect_uri="http://x")

    def test_empty_secret_rejected(self) -> None:
        with pytest.raises(ValueError):
            OAuthClient(client_id="x", client_secret="", redirect_uri="http://x")

    def test_empty_redirect_uri_rejected(self) -> None:
        with pytest.raises(ValueError):
            OAuthClient(client_id="x", client_secret="y", redirect_uri="")
