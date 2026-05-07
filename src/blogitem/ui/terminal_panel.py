"""TerminalPanel — 임베디드 터미널 위젯.

CLI subprocess 의 라인별 stdout 을 실시간 표시 + 사용자 ad-hoc 프롬프트 입력.

레이아웃:
    ┌─ 상태 라벨 (현재 LLM 모드 + 마지막 호출) ─┐
    │  [출력 영역 — monospace + 자동 스크롤]     │
    │                                             │
    ├─────────────────────────────────────────────┤
    │ [입력 필드]                    [Send] [지우기]│
    └─────────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from blogitem.config import Settings


_KIND_COLOR: dict[str, str] = {
    "info": "#7a756c",
    "stdout": "#0a0908",
    "user": "#1d4d8a",
    "assistant": "#063",
    "error": "#c4623c",
    "system": "#7a756c",
}


class TerminalPanel(QWidget):
    """터미널처럼 보이는 출력 영역 + 입력 필드.

    Signals:
        prompt_submitted(str): 사용자가 입력 필드에서 Send 눌렀을 때.
    """

    prompt_submitted = Signal(str)

    def __init__(
        self,
        *,
        settings: Settings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings

        # 상태 라벨
        self._status = QLabel(self._compose_status())
        self._status.setStyleSheet(
            "padding: 6px 10px; background: #ebe4d2; "
            "color: #4a4742; font-size: 11px; "
            "font-family: 'JetBrains Mono', Consolas, monospace;"
        )

        # 출력 영역
        self._output = QPlainTextEdit(self)
        self._output.setReadOnly(True)
        self._output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        mono = QFont("JetBrains Mono", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._output.setFont(mono)
        self._output.setStyleSheet(
            "QPlainTextEdit { background: #fcfaf3; border: 1px solid #d9d0bc; }"
        )

        # 입력 줄
        self._input = QLineEdit(self)
        self._input.setPlaceholderText("프롬프트 입력 (현재 LLM 모드로 호출) — Enter 또는 Send")
        self._input.setFont(mono)
        self._input.returnPressed.connect(self._on_submit)

        send_btn = QPushButton("Send", self)
        send_btn.clicked.connect(self._on_submit)

        clear_btn = QPushButton("지우기", self)
        clear_btn.clicked.connect(self.clear_output)

        input_row = QHBoxLayout()
        input_row.addWidget(self._input, stretch=1)
        input_row.addWidget(send_btn)
        input_row.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._status)
        layout.addWidget(self._output, stretch=1)
        layout.addLayout(input_row)

    # ── 외부 API ────────────────────────────────────────────────────────────

    def append_line(self, line: str, *, kind: str = "stdout") -> None:
        """한 줄 추가 (자동 스크롤)."""
        color = _KIND_COLOR.get(kind, _KIND_COLOR["stdout"])
        cursor = self._output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        fmt.setForeground(Qt.GlobalColor.black if kind == "stdout" else Qt.GlobalColor.gray)
        # 컬러는 HTML 직접 삽입으로 — QTextCharFormat 는 setForeground(QColor) 가 깔끔하지만
        # 여기서는 단순화 위해 appendHtml.
        from html import escape

        prefix = ""
        if kind == "user":
            prefix = "▶ "
        elif kind == "assistant":
            prefix = "◀ "
        elif kind == "error":
            prefix = "⚠ "

        html = f'<span style="color: {color}; white-space: pre-wrap;">{escape(prefix + line)}</span>'
        self._output.appendHtml(html)

        # 자동 스크롤 (사용자가 위로 스크롤한 상태가 아니면)
        bar = self._output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def append_block(self, text: str, *, kind: str = "stdout") -> None:
        """여러 줄 한 번에 추가."""
        for line in text.splitlines() or [text]:
            self.append_line(line, kind=kind)

    def clear_output(self) -> None:
        self._output.clear()

    def update_status(self, message: str | None = None) -> None:
        text = self._compose_status()
        if message:
            text = f"{text}  ·  {message}"
        self._status.setText(text)

    def set_busy(self, busy: bool) -> None:
        """입력 필드 비활성화 (호출 진행 중)."""
        self._input.setEnabled(not busy)

    # ── 내부 ────────────────────────────────────────────────────────────────

    def _compose_status(self) -> str:
        mode = (self._settings.llm_mode or "api").strip().lower()
        model = (
            self._settings.llm_cli_model
            or self._settings.claude_model_primary
            or "(default)"
        )
        return f"LLM mode: {mode}  ·  model: {model}"

    def _on_submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self.append_line(text, kind="user")
        self.prompt_submitted.emit(text)
