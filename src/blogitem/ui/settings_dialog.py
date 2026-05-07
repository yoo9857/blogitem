"""설정 다이얼로그 — Anthropic API 키 + 네이버 OAuth 자격증명 + 인증 흐름."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from blogitem import secrets

if TYPE_CHECKING:
    from blogitem.ui.workers.oauth_worker import OAuthWorker


class SettingsDialog(QDialog):
    """API 키 / OAuth 자격증명 입력 + 네이버 연결 흐름."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("blogitem · 설정")
        self.setMinimumWidth(560)

        self._oauth_worker: OAuthWorker | None = None
        self._oauth_progress: QProgressDialog | None = None

        tabs = QTabWidget(self)
        tabs.addTab(self._build_anthropic_tab(), "Anthropic")
        tabs.addTab(self._build_naver_tab(), "네이버")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    # ── Tabs ────────────────────────────────────────────────────────────────

    def _build_anthropic_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)

        self._anthropic_key = QLineEdit(w)
        self._anthropic_key.setEchoMode(QLineEdit.EchoMode.Password)
        if secrets.get_optional("anthropic_api_key"):
            self._anthropic_key.setPlaceholderText(
                "● ● ● ● (저장됨 — 변경 시에만 입력)"
            )

        form.addRow("API Key:", self._anthropic_key)

        info = QLabel(
            '<a href="https://console.anthropic.com/settings/keys">'
            "console.anthropic.com/settings/keys</a> 에서 발급."
        )
        info.setOpenExternalLinks(True)
        form.addRow(info)

        return w

    def _build_naver_tab(self) -> QWidget:
        w = QWidget(self)
        form = QFormLayout(w)

        self._naver_client_id = QLineEdit(w)
        self._naver_client_id.setText(secrets.get_optional("naver_oauth_client_id") or "")

        self._naver_client_secret = QLineEdit(w)
        self._naver_client_secret.setEchoMode(QLineEdit.EchoMode.Password)
        if secrets.get_optional("naver_oauth_client_secret"):
            self._naver_client_secret.setPlaceholderText(
                "● ● ● ● (저장됨 — 변경 시에만 입력)"
            )

        connect_btn = QPushButton("네이버 연결…", w)
        connect_btn.clicked.connect(self._start_oauth)

        disconnect_btn = QPushButton("토큰 폐기", w)
        disconnect_btn.clicked.connect(self._clear_tokens)

        form.addRow("Client ID:", self._naver_client_id)
        form.addRow("Client Secret:", self._naver_client_secret)
        form.addRow("연결:", connect_btn)
        form.addRow("재인증:", disconnect_btn)

        info = QLabel(
            '<a href="https://developers.naver.com">developers.naver.com</a> '
            "에서 애플리케이션 등록 → Callback URL: "
            "<code>http://127.0.0.1:8765/naver-callback</code>"
        )
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        form.addRow(info)

        return w

    # ── Save ────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            ak = self._anthropic_key.text().strip()
            if ak:
                secrets.set_secret("anthropic_api_key", ak)

            cid = self._naver_client_id.text().strip()
            if cid:
                secrets.set_secret("naver_oauth_client_id", cid)

            csec = self._naver_client_secret.text().strip()
            if csec:
                secrets.set_secret("naver_oauth_client_secret", csec)

            self.accept()
        except Exception as e:  # noqa: BLE001
            # keyring 예외는 시크릿 값을 포함하지 않지만 보수적으로 type 만 표시
            QMessageBox.critical(
                self,
                "저장 실패",
                f"시크릿 저장 중 오류:\n{type(e).__name__}: {e}",
            )

    # ── OAuth 흐름 ──────────────────────────────────────────────────────────

    def _start_oauth(self) -> None:
        # 자격증명 확보 — 폼 입력 우선, 없으면 keyring 에서
        cid = (
            self._naver_client_id.text().strip()
            or secrets.get_optional("naver_oauth_client_id")
            or ""
        )
        csec = (
            self._naver_client_secret.text().strip()
            or secrets.get_optional("naver_oauth_client_secret")
            or ""
        )
        if not cid or not csec:
            QMessageBox.warning(
                self,
                "OAuth",
                "Client ID 와 Secret 을 먼저 입력하고 [저장] 후 다시 시도하세요.",
            )
            return

        # Settings 의 콜백 호스트/포트 사용
        from blogitem.config import load_settings
        from blogitem.naver.oauth import OAuthClient
        from blogitem.ui.workers.oauth_worker import OAuthWorker

        settings = load_settings()
        redirect_uri = (
            f"http://{settings.oauth_callback_host}:{settings.oauth_callback_port}/naver-callback"
        )

        client = OAuthClient(
            client_id=cid,
            client_secret=csec,
            redirect_uri=redirect_uri,
        )

        self._oauth_progress = QProgressDialog(
            "브라우저에서 동의를 완료하세요. 5분 안에 완료되지 않으면 취소됩니다.",
            "취소",
            0,
            0,
            self,
        )
        self._oauth_progress.setWindowTitle("네이버 연결")
        self._oauth_progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._oauth_progress.setMinimumDuration(0)

        self._oauth_worker = OAuthWorker(
            client=client,
            host=settings.oauth_callback_host,
            port=settings.oauth_callback_port,
        )
        self._oauth_worker.finished_ok.connect(self._on_oauth_ok)
        self._oauth_worker.failed.connect(self._on_oauth_fail)
        self._oauth_progress.canceled.connect(self._oauth_worker.cancel)
        # finished 는 ok / fail 양쪽 종료 시 모두 emit — progress 닫기에 사용
        self._oauth_worker.finished.connect(self._oauth_progress.close)

        self._oauth_worker.start()
        self._oauth_progress.exec()

    def _on_oauth_ok(self, tokens: dict) -> None:
        from blogitem.naver.token_store import TokenStore

        try:
            TokenStore().save_pair(
                access_token=str(tokens["access_token"]),
                refresh_token=str(tokens.get("refresh_token") or ""),
                expires_in=int(tokens.get("expires_in") or 3600),
            )
            QMessageBox.information(
                self,
                "연결 완료",
                "네이버 OAuth 인증 성공. 토큰이 저장되었습니다.",
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "토큰 저장 실패",
                f"{type(e).__name__}: {e}",
            )

    def _on_oauth_fail(self, message: str) -> None:
        QMessageBox.critical(self, "연결 실패", message)

    def _clear_tokens(self) -> None:
        from blogitem.naver.token_store import TokenStore

        confirm = QMessageBox.question(
            self,
            "토큰 폐기",
            "저장된 access/refresh 토큰을 삭제합니다. 다음 게시 시 재인증이 필요합니다. 진행할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            TokenStore().clear()
            QMessageBox.information(self, "토큰 폐기", "토큰이 삭제되었습니다.")
