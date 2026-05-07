"""네이버 OAuth 2.0 — authorization code 흐름 (PKCE 옵션).

데스크톱 앱 흐름:
    1. ``build_authorize_url(state)`` — 브라우저로 열 URL 생성.
    2. 임시 ``http://127.0.0.1:8765/callback`` HTTP 서버 띄움 (CallbackServer).
    3. 사용자가 네이버 동의 후 → 콜백으로 ``code`` + ``state`` 도착.
    4. ``exchange_code(code)`` — code → access_token + refresh_token 교환.
    5. refresh_token 은 ``TokenStore`` (keyring) 에 저장.
    6. access_token 만료 시 ``refresh()`` — refresh_token 으로 갱신.
       Naver 의 refresh_token 은 갱신 시 회전될 수 있음 → 결과를 다시 저장.

P1 — 본격 구현.
"""

from __future__ import annotations

from urllib.parse import urlencode


AUTHORIZE_URL = "https://nid.naver.com/oauth2.0/authorize"
TOKEN_URL = "https://nid.naver.com/oauth2.0/token"


class OAuthClient:
    """네이버 OAuth 2.0 client."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("client_id / client_secret required")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    def build_authorize_url(self, state: str) -> str:
        """동의 URL 생성. ``state`` 는 CSRF 토큰 — 콜백에서 검증 필수."""
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, state: str) -> dict[str, str | int]:
        """code → ``{access_token, refresh_token, expires_in, token_type}`` 교환."""
        raise NotImplementedError("P1 — httpx POST 구현 필요")

    def refresh(self, refresh_token: str) -> dict[str, str | int]:
        """refresh_token → 새 ``{access_token, refresh_token, expires_in}``."""
        raise NotImplementedError("P1 — 구현 필요")


class CallbackServer:
    """``http.server`` 기반 임시 HTTP 서버.

    ``start()`` → 백그라운드 스레드. ``wait_for_callback(timeout)`` → ``code``+``state`` 반환.
    P1 — 구현 필요.
    """

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    def start(self) -> None:
        raise NotImplementedError("P1 — 구현 필요")

    def wait_for_callback(self, timeout_sec: int = 300) -> tuple[str, str]:
        """code, state 반환. 시간 초과 시 ``TimeoutError``."""
        raise NotImplementedError("P1 — 구현 필요")

    def stop(self) -> None:
        raise NotImplementedError("P1 — 구현 필요")
