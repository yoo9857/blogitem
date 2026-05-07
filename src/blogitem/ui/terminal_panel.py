"""TerminalPanel — 임베디드 터미널 위젯.

CLI subprocess 의 라인별 stdout 을 실시간 표시 + 사용자 ad-hoc 프롬프트 입력.

기능:
    · monospace 출력 영역 + 자동 스크롤
    · 라인별 색상 (info/stdout/user/assistant/error)
    · 턴 구분선 — user 입력마다 가로선 + 시각 라벨
    · 스크롤백 자동 트리밍 (기본 5,000 블록)
    · "저장" 버튼 — 전체 출력을 .log 파일로 내보내기
"""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
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

_KIND_PREFIX: dict[str, str] = {
    "user": "▶ ",
    "assistant": "◀ ",
    "error": "⚠ ",
}

#: 출력 영역 최대 블록 수 — 초과 시 오래된 블록부터 삭제
_DEFAULT_MAX_BLOCKS = 5000


class TerminalPanel(QWidget):
    """터미널처럼 보이는 출력 영역 + 입력 필드 + 저장.

    Signals:
        prompt_submitted(str): 사용자가 Send 또는 Enter 눌렀을 때.
    """

    prompt_submitted = Signal(str)

    def __init__(
        self,
        *,
        settings: Settings,
        parent: QWidget | None = None,
        max_blocks: int = _DEFAULT_MAX_BLOCKS,
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
        self._output.setMaximumBlockCount(max_blocks)  # 자동 스크롤백 트리밍
        mono = QFont("JetBrains Mono", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._output.setFont(mono)
        self._output.setStyleSheet(
            "QPlainTextEdit { background: #fcfaf3; border: 1px solid #d9d0bc; }"
        )

        # 입력 줄
        self._input = QLineEdit(self)
        self._input.setPlaceholderText(
            "프롬프트 입력 (현재 LLM 모드로 호출) — Enter 또는 Send"
        )
        self._input.setFont(mono)
        self._input.returnPressed.connect(self._on_submit)

        send_btn = QPushButton("Send", self)
        send_btn.clicked.connect(self._on_submit)

        save_btn = QPushButton("저장", self)
        save_btn.setToolTip("출력 영역 전체를 .log 파일로 저장")
        save_btn.clicked.connect(self._save_output)

        clear_btn = QPushButton("지우기", self)
        clear_btn.clicked.connect(self.clear_output)

        input_row = QHBoxLayout()
        input_row.addWidget(self._input, stretch=1)
        input_row.addWidget(send_btn)
        input_row.addWidget(save_btn)
        input_row.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._status)
        layout.addWidget(self._output, stretch=1)
        layout.addLayout(input_row)

    # ── 외부 API ────────────────────────────────────────────────────────────

    def append_line(self, line: str, *, kind: str = "stdout") -> None:
        """한 줄 추가 (자동 스크롤 + 라인별 색상)."""
        color = _KIND_COLOR.get(kind, _KIND_COLOR["stdout"])
        prefix = _KIND_PREFIX.get(kind, "")

        html = (
            f'<span style="color: {color}; white-space: pre-wrap;">'
            f"{escape(prefix + line)}</span>"
        )
        self._output.appendHtml(html)

        bar = self._output.verticalScrollBar()
        bar.setValue(bar.maximum())

    def append_block(self, text: str, *, kind: str = "stdout") -> None:
        """여러 줄 한 번에 추가."""
        for line in text.splitlines() or [text]:
            self.append_line(line, kind=kind)

    def append_turn_separator(self, label: str | None = None) -> None:
        """대화 턴 구분선 추가 — 시각적 휴식 + 시각 라벨."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        marker = f"── {label} · {timestamp} ──" if label else f"── {timestamp} ──"
        html = (
            '<div style="color: #d9d0bc; padding: 4px 0; '
            'border-top: 1px dashed #d9d0bc; font-size: 10px;">'
            f"{escape(marker)}"
            "</div>"
        )
        self._output.appendHtml(html)
        bar = self._output.verticalScrollBar()
        bar.setValue(bar.maximum())

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

    def plain_text(self) -> str:
        """출력 영역의 평문 (저장용)."""
        return self._output.toPlainText()

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
        self.append_turn_separator(label="user prompt")
        self.append_line(text, kind="user")
        self.prompt_submitted.emit(text)

    def _save_output(self) -> None:
        """전체 출력을 timestamped .log 파일로 저장."""
        default_name = f"blogitem-terminal-{datetime.now():%Y%m%d-%H%M%S}.log"
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "터미널 출력 저장",
            default_name,
            "Log files (*.log);;Text files (*.txt);;All files (*.*)",
        )
        if not path_str:
            return
        try:
            from pathlib import Path

            Path(path_str).write_text(self.plain_text(), encoding="utf-8")
        except OSError as e:
            QMessageBox.critical(self, "저장 실패", f"{type(e).__name__}: {e}")
            return
        self.update_status(message=f"saved → {path_str}")
