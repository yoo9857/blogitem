"""ImagePromptsDialog — Claude 가 생성한 이미지 프롬프트 N+1개를 리스트로 표시.

각 프롬프트마다 [클립보드 복사] + [ChatGPT 열기] 버튼. 사용자가 클릭 한 번으로
프롬프트를 ChatGPT 웹에 붙여넣어 이미지 생성.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    pass


CHATGPT_URL = "https://chatgpt.com/"


_ROLE_LABEL = {
    "thumbnail": "🖼 썸네일",
    "body": "📄 본문",
}


class _PromptCard(QFrame):
    """단일 프롬프트 카드 — 역할/목적 + 프롬프트 textarea + 복사/열기 버튼."""

    def __init__(self, item: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { border: 1px solid #d9d0bc; border-radius: 4px; "
            "padding: 10px; background: #fff; }"
        )

        role = str(item.get("role") or "")
        position = item.get("position") or 0
        purpose = str(item.get("purpose") or "")
        prompt_text = str(item.get("prompt") or "")

        role_lbl_text = _ROLE_LABEL.get(role, role) or "—"
        if role == "body":
            role_lbl_text = f"{role_lbl_text} #{position}"

        header = QHBoxLayout()
        role_lbl = QLabel(f"<b>{role_lbl_text}</b>")
        role_lbl.setStyleSheet("font-size: 13px; color: #0a0908;")
        purpose_lbl = QLabel(purpose)
        purpose_lbl.setStyleSheet("color: #4a4742; font-size: 12px;")
        purpose_lbl.setWordWrap(True)
        header.addWidget(role_lbl)
        header.addStretch(1)

        self._editor = QPlainTextEdit()
        self._editor.setPlainText(prompt_text)
        self._editor.setStyleSheet(
            "QPlainTextEdit { font-family: 'JetBrains Mono', Consolas, monospace; "
            "font-size: 11px; background: #fcfaf3; border: 1px solid #ebe4d2; "
            "padding: 8px; }"
        )
        self._editor.setMinimumHeight(110)

        copy_btn = QPushButton("📋 클립보드 복사")
        copy_btn.clicked.connect(self._copy)
        open_btn = QPushButton("🌐 ChatGPT 열기")
        open_btn.clicked.connect(self._open_chatgpt)
        copy_open_btn = QPushButton("📋 복사 + ChatGPT 열기")
        copy_open_btn.setStyleSheet(
            "QPushButton { background: #c4623c; color: #fff; padding: 8px 14px; "
            "border-radius: 3px; font-weight: 600; }"
        )
        copy_open_btn.clicked.connect(self._copy_and_open)

        action_row = QHBoxLayout()
        action_row.addWidget(copy_btn)
        action_row.addWidget(open_btn)
        action_row.addStretch(1)
        action_row.addWidget(copy_open_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(header)
        layout.addWidget(purpose_lbl)
        layout.addWidget(self._editor)
        layout.addLayout(action_row)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._editor.toPlainText())

    def _open_chatgpt(self) -> None:
        QDesktopServices.openUrl(QUrl(CHATGPT_URL))

    def _copy_and_open(self) -> None:
        self._copy()
        self._open_chatgpt()


class ImagePromptsDialog(QDialog):
    """이미지 프롬프트 다이얼로그.

    사용자 흐름:
        1. 다이얼로그 열림 → 카드 N+1 개 (썸네일 1 + 본문 N).
        2. [복사 + ChatGPT 열기] 클릭 → 프롬프트 클립보드 + 브라우저.
        3. ChatGPT 에 붙여넣고 이미지 생성 + 다운로드.
        4. 닫고 → blogitem 의 "다운로드 임포트" 또는 워치 폴더가 자동 감지.
    """

    def __init__(
        self,
        *,
        prompts_data: dict[str, object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Claude 이미지 프롬프트")
        self.setMinimumSize(820, 640)

        # 헤더 — 스타일 가이드
        style_guide = str(prompts_data.get("style_guide") or "")
        header_lbl = QLabel(
            f"<b>스타일 가이드:</b> {style_guide}" if style_guide else
            "Claude 가 생성한 이미지 프롬프트입니다 — 각 프롬프트를 ChatGPT 에 붙여넣어 이미지를 만드세요."
        )
        header_lbl.setWordWrap(True)
        header_lbl.setStyleSheet(
            "padding: 10px; background: #ebe4d2; color: #0a0908; "
            "border-radius: 3px; font-size: 12px;"
        )

        # 카드 스택
        cards_container = QWidget()
        cards_layout = QVBoxLayout(cards_container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(8)

        items = prompts_data.get("images") or []
        if isinstance(items, list):
            # 썸네일 먼저 (role=thumbnail), 그다음 본문 position 오름차순.
            sorted_items = sorted(
                (i for i in items if isinstance(i, dict)),
                key=lambda it: (
                    0 if it.get("role") == "thumbnail" else 1,
                    int(it.get("position") or 0),
                ),
            )
            for item in sorted_items:
                cards_layout.addWidget(_PromptCard(item))
        else:
            cards_layout.addWidget(QLabel("(이미지 프롬프트가 없습니다 — 응답 형식 확인 필요)"))

        # raw 폴백 표시
        if "raw" in prompts_data:
            raw_label = QLabel("<b>원본 응답 (JSON 파싱 실패):</b>")
            raw_text = QPlainTextEdit(str(prompts_data.get("raw") or ""))
            raw_text.setReadOnly(True)
            raw_text.setMaximumHeight(180)
            cards_layout.addWidget(raw_label)
            cards_layout.addWidget(raw_text)

        cards_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(cards_container)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        # 닫기
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(header_lbl)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(buttons)
