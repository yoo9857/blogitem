"""설정 다이얼로그 — Anthropic API 키 + 네이버 OAuth 자격증명.

저장 시 keyring 에 즉시 반영. 빈 입력은 변경 없음으로 간주.
P0 — 입력·저장만. OAuth 동의 흐름은 P1.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from blogitem import secrets


class SettingsDialog(QDialog):
    """API 키 / OAuth 자격증명 입력."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("blogitem · 설정")
        self.setMinimumWidth(560)

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

        form.addRow("Client ID:", self._naver_client_id)
        form.addRow("Client Secret:", self._naver_client_secret)
        form.addRow("연결:", connect_btn)

        info = QLabel(
            '<a href="https://developers.naver.com">developers.naver.com</a> '
            "에서 애플리케이션 등록 → Callback URL: "
            "<code>http://127.0.0.1:8765/naver-callback</code>"
        )
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        form.addRow(info)

        return w

    # ── Actions ─────────────────────────────────────────────────────────────

    def _save(self) -> None:
        try:
            ak = self._anthropic_key.text().strip()
            if ak:
                secrets.set_secret("anthropic_api_key", ak)

            cid = self._naver_client_id.text().strip()
            if cid:
                secrets.set_secret("naver_oauth_client_id", cid)
            elif self._naver_client_id.text() == "" and secrets.get_optional(
                "naver_oauth_client_id"
            ):
                # 기존 값 비우기 — 사용자가 명시적으로 빈 값으로 변경한 경우만 삭제
                pass  # P0 에서는 삭제 동작 없음. 명시적 "토큰 폐기" 버튼으로 처리.

            csec = self._naver_client_secret.text().strip()
            if csec:
                secrets.set_secret("naver_oauth_client_secret", csec)

            self.accept()
        except Exception as e:
            # 시크릿 값이 메시지에 노출되지 않도록 e 만 표시 (keyring 예외엔 값이 없음)
            QMessageBox.critical(
                self,
                "저장 실패",
                f"시크릿 저장 중 오류:\n{type(e).__name__}: {e}",
            )

    def _start_oauth(self) -> None:
        QMessageBox.information(
            self,
            "OAuth 연결",
            "네이버 OAuth 인증 흐름은 P1 에서 구현 예정입니다.\n"
            "현재는 Client ID / Client Secret 만 저장합니다.",
        )
