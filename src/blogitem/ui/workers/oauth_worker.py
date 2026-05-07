"""OAuthWorker — UI 스레드 차단 없이 네이버 OAuth 흐름 실행.

PySide6 ``QThread`` 상속. 콜백 서버 + 토큰 교환을 별도 스레드에서 수행하고,
완료/실패를 시그널로 메인 윈도우에 전달.

시그널:
    · finished_ok(dict)  — ``{access_token, refresh_token, expires_in, token_type}``
    · failed(str)         — 사용자에게 표시할 에러 메시지
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

from blogitem.naver.oauth import CallbackServer, OAuthError, build_state

if TYPE_CHECKING:
    from blogitem.naver.oauth import OAuthClient


class OAuthWorker(QThread):
    """OAuth 흐름 백그라운드 실행."""

    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(
        self,
        *,
        client: OAuthClient,
        host: str,
        port: int,
        timeout_sec: int = 300,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._client = client
        self._host = host
        self._port = port
        self._timeout_sec = timeout_sec
        self._server: CallbackServer | None = None

    def run(self) -> None:  # noqa: D401 — QThread.run override
        try:
            state = build_state()
            auth_url = self._client.build_authorize_url(state)

            self._server = CallbackServer(self._host, self._port)
            self._server.start()
            try:
                self._open_browser(auth_url)
                code, returned_state = self._server.wait_for_callback(
                    timeout_sec=self._timeout_sec
                )
                if returned_state != state:
                    raise OAuthError("state mismatch — CSRF 의심", retryable=False)
                tokens = self._client.exchange_code(code, returned_state)
                self.finished_ok.emit(dict(tokens))
            finally:
                self._server.stop()
        except TimeoutError as e:
            self.failed.emit(f"시간 초과: {e}")
        except OAuthError as e:
            self.failed.emit(f"OAuth 실패: {e}")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")

    def cancel(self) -> None:
        """진행 중인 OAuth 흐름 취소 — 콜백 서버 종료 + 대기자 깨움."""
        if self._server is not None:
            self._server.stop()
        self.requestInterruption()

    @staticmethod
    def _open_browser(url: str) -> None:
        """기본 브라우저 열기 — Qt 우선, 실패 시 stdlib fallback."""
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices

            if QDesktopServices.openUrl(QUrl(url)):
                return
        except ImportError:
            pass
        import webbrowser

        webbrowser.open(url, new=1, autoraise=True)
