"""네이버 OAuth 2.0 — authorization code 흐름 + localhost 콜백 서버.

데스크톱 앱 흐름:
    1. ``build_state()`` — CSRF 방지 토큰.
    2. ``OAuthClient.build_authorize_url(state)`` — 브라우저로 열 URL.
    3. ``CallbackServer.start()`` — 임시 ``http://127.0.0.1:8765/naver-callback``.
    4. 사용자가 네이버 동의 후 → 콜백으로 ``code`` + ``state`` 도착.
    5. ``OAuthClient.exchange_code(code, state)`` → access/refresh 토큰.
    6. refresh_token 은 ``TokenStore`` (keyring) 에 저장.
    7. access_token 만료 시 ``OAuthClient.refresh()`` — refresh_token 으로 갱신.
       Naver 의 refresh_token 은 갱신 시 회전될 수 있음 → 결과를 다시 저장.
"""

from __future__ import annotations

import http.server
import threading
from secrets import token_urlsafe
from typing import Final
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

AUTHORIZE_URL: Final = "https://nid.naver.com/oauth2.0/authorize"
TOKEN_URL: Final = "https://nid.naver.com/oauth2.0/token"
CALLBACK_PATH: Final = "/naver-callback"

_TIMEOUT_SEC: Final = 15


# ── 응답 페이지 (콜백 후 브라우저에 보여줌) ─────────────────────────────────────

_SUCCESS_HTML = """\
<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>blogitem · 인증 완료</title>
<style>body{font-family:-apple-system,system-ui,sans-serif;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0;background:#f3efe5;color:#0a0908}
.box{text-align:center;padding:40px}h1{margin:0 0 12px;font-size:22px}p{color:#7a756c}</style>
</head><body><div class="box"><h1>✓ 인증 완료</h1><p>blogitem 으로 돌아가도 됩니다. 이 창은 닫아주세요.</p></div></body></html>
"""

_FAILURE_HTML = """\
<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>blogitem · 인증 실패</title>
<style>body{font-family:-apple-system,system-ui,sans-serif;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0;background:#fcf0e9;color:#c4623c}
.box{text-align:center;padding:40px}h1{margin:0 0 12px;font-size:22px}</style>
</head><body><div class="box"><h1>⚠ 인증 실패</h1><p>blogitem 에서 자세한 내용을 확인하세요.</p></div></body></html>
"""


class OAuthError(RuntimeError):
    """네이버 OAuth 호출 실패."""

    def __init__(self, message: str, *, status_code: int = 0, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


def build_state() -> str:
    """CSRF 방지 state 토큰 — 256-bit URL-safe."""
    return token_urlsafe(32)


# ── OAuth 클라이언트 ────────────────────────────────────────────────────────────


class OAuthClient:
    """네이버 OAuth 2.0 client — 토큰 교환·갱신 담당.

    단일 책임: HTTP 호출만. 콜백 서버나 토큰 저장은 별도 컴포넌트.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
    ) -> None:
        if not client_id or not client_secret:
            raise ValueError("client_id / client_secret required")
        if not redirect_uri:
            raise ValueError("redirect_uri required")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri

    def build_authorize_url(self, state: str) -> str:
        """동의 URL 생성.

        Args:
            state: CSRF 방지 토큰. 콜백에서 동일성 검증 필수.
        """
        if not state:
            raise ValueError("state required")
        params = {
            "response_type": "code",
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "state": state,
        }
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, state: str) -> dict[str, object]:
        """code → access_token / refresh_token 교환.

        Returns:
            ``{access_token, refresh_token, expires_in (int), token_type}``.
        """
        if not code or not state:
            raise ValueError("code and state required")
        return self._post_token({
            "grant_type": "authorization_code",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "code": code,
            "state": state,
        })

    def refresh(self, refresh_token: str) -> dict[str, object]:
        """refresh_token → 새 access_token (+ 회전된 refresh_token).

        Returns:
            ``{access_token, refresh_token, expires_in (int), token_type}``.
        """
        if not refresh_token:
            raise ValueError("refresh_token required")
        return self._post_token({
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": refresh_token,
        })

    def _post_token(self, params: dict[str, str]) -> dict[str, object]:
        """``POST {TOKEN_URL}`` — form-encoded body. 시크릿은 예외에 절대 노출 X."""
        try:
            resp = httpx.post(TOKEN_URL, data=params, timeout=_TIMEOUT_SEC)
        except httpx.TimeoutException as e:
            raise OAuthError("network: timeout", retryable=True) from e
        except httpx.RequestError as e:
            # str(e) 에 client_secret 등이 들어가지 않도록 type 만 사용
            raise OAuthError(f"network: {type(e).__name__}", retryable=True) from e

        # Naver 는 200 응답에도 error 필드를 담을 수 있음 — JSON 먼저 본다.
        try:
            data = resp.json()
        except ValueError as e:
            raise OAuthError(
                f"non-JSON response (HTTP {resp.status_code})",
                status_code=resp.status_code,
                retryable=resp.status_code >= 500,
            ) from e

        if "error" in data:
            err = str(data.get("error", "unknown"))
            desc = str(data.get("error_description", ""))[:200]
            raise OAuthError(f"{err}: {desc}", status_code=resp.status_code, retryable=False)

        if resp.status_code >= 500:
            raise OAuthError(
                f"server error HTTP {resp.status_code}",
                status_code=resp.status_code,
                retryable=True,
            )
        if resp.status_code != 200:
            raise OAuthError(
                f"HTTP {resp.status_code}",
                status_code=resp.status_code,
                retryable=False,
            )

        try:
            return {
                "access_token": str(data["access_token"]),
                "refresh_token": str(data.get("refresh_token", "")),
                "expires_in": int(data.get("expires_in", 3600)),
                "token_type": str(data.get("token_type", "Bearer")),
            }
        except (KeyError, ValueError, TypeError) as e:
            raise OAuthError("malformed token response", retryable=False) from e


# ── 콜백 서버 (브라우저 redirect 캡처) ──────────────────────────────────────────


class CallbackServer:
    """``http.server`` 기반 임시 HTTP 서버 — OAuth 콜백 1회 캡처.

    스레드 안전: ``start()`` 후 ``wait_for_callback()`` 은 다른 스레드에서 OK.
    ``stop()`` 호출 시 대기 중인 ``wait_for_callback()`` 은 ``OAuthError("cancelled")`` raise.
    """

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._result_event = threading.Event()
        self._result: tuple[str | None, str | None, str | None] = (None, None, None)
        # (code, state, error_msg)

    def start(self) -> None:
        """서버 시작 + 백그라운드 스레드에서 ``serve_forever``."""
        handler_cls = self._make_handler_cls()
        try:
            self._server = http.server.HTTPServer((self._host, self._port), handler_cls)
        except OSError as e:
            raise OAuthError(
                f"콜백 포트 {self._port} 사용 중 — 다른 프로세스 종료 후 재시도",
                retryable=False,
            ) from e

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="naver-oauth-callback",
            daemon=True,
        )
        self._thread.start()

    def wait_for_callback(self, timeout_sec: int = 300) -> tuple[str, str]:
        """콜백 도착 대기. ``(code, state)`` 반환.

        Raises:
            TimeoutError: 시간 초과.
            OAuthError: 사용자 거절 또는 서버 측 에러 응답.
        """
        if not self._result_event.wait(timeout_sec):
            raise TimeoutError(f"OAuth 콜백 {timeout_sec}s 안에 도착하지 않음")
        code, state, err = self._result
        if err is not None:
            raise OAuthError(err, retryable=False)
        if code is None or state is None:
            raise OAuthError("콜백 응답 누락", retryable=False)
        return code, state

    def stop(self) -> None:
        """서버 종료 + 대기자 즉시 깨움."""
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:  # noqa: BLE001 — 이미 종료된 서버 정리 중 예외는 무시
                pass
            self._server = None
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
            self._thread = None
        if not self._result_event.is_set():
            self._result = (None, None, "cancelled")
            self._result_event.set()

    # ── private ─────────────────────────────────────────────────────────────

    def _make_handler_cls(self) -> type[http.server.BaseHTTPRequestHandler]:
        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != CALLBACK_PATH:
                    self.send_error(404, "Not Found")
                    return

                qs = parse_qs(parsed.query)
                code = (qs.get("code") or [""])[0]
                state = (qs.get("state") or [""])[0]
                error = (qs.get("error") or [""])[0]
                error_desc = (qs.get("error_description") or [""])[0]

                if error:
                    body = _FAILURE_HTML.encode("utf-8")
                    outer._result = (None, None, f"{error}: {error_desc}")
                elif code and state:
                    body = _SUCCESS_HTML.encode("utf-8")
                    outer._result = (code, state, None)
                else:
                    body = _FAILURE_HTML.encode("utf-8")
                    outer._result = (None, None, "missing code/state")

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

                outer._result_event.set()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                # 기본 stderr 로깅 끔 — blogitem 의 structlog 로 별도 기록.
                return

        return _Handler


# ── 통합 흐름 ──────────────────────────────────────────────────────────────────


def perform_oauth_flow(
    *,
    client: OAuthClient,
    host: str,
    port: int,
    open_browser: bool = True,
    timeout_sec: int = 300,
) -> dict[str, object]:
    """OAuth 전체 흐름 실행 (블로킹).

    Args:
        client: ``OAuthClient`` 인스턴스.
        host: 콜백 서버 호스트 (보통 127.0.0.1).
        port: 콜백 서버 포트 (네이버 등록값과 동일).
        open_browser: ``QDesktopServices.openUrl`` 실패 시 fallback 으로 ``webbrowser``.
        timeout_sec: 콜백 대기 시간.

    Returns:
        토큰 딕셔너리 (``exchange_code`` 결과와 동일 형식).

    Raises:
        OAuthError: 인증 실패.
        TimeoutError: 시간 초과.
    """
    state = build_state()
    auth_url = client.build_authorize_url(state)

    server = CallbackServer(host, port)
    server.start()
    try:
        if open_browser:
            _open_url(auth_url)
        code, returned_state = server.wait_for_callback(timeout_sec=timeout_sec)
        if returned_state != state:
            raise OAuthError("state mismatch — CSRF 의심", retryable=False)
        return client.exchange_code(code, returned_state)
    finally:
        server.stop()


def _open_url(url: str) -> None:
    """기본 브라우저 열기 — Qt 우선, 실패 시 stdlib webbrowser fallback."""
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        if QDesktopServices.openUrl(QUrl(url)):
            return
    except ImportError:
        pass
    import webbrowser

    webbrowser.open(url, new=1, autoraise=True)
