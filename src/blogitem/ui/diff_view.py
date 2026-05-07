"""DiffView — 좌·우 두 본문 side-by-side 비교 (3.초고 vs 4.인간화).

P4 — 단순 dual editor + 라인 단위 diff 하이라이트 (difflib 기반).
"""

from __future__ import annotations

import difflib

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)


_INSERT_BG = QColor(220, 245, 220)
_DELETE_BG = QColor(252, 220, 220)
_REPLACE_BG = QColor(255, 240, 200)


class DiffView(QWidget):
    """좌(원본) / 우(수정본) 비교. 라인 단위 색상 하이라이트."""

    def __init__(
        self,
        *,
        left_label: str = "원본",
        right_label: str = "수정본",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._left = QPlainTextEdit(self)
        self._left.setReadOnly(True)
        self._right = QPlainTextEdit(self)
        self._right.setReadOnly(True)

        for editor in (self._left, self._right):
            editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            editor.setStyleSheet(
                "QPlainTextEdit { font-family: 'JetBrains Mono', Consolas, monospace; "
                "font-size: 12px; }"
            )

        # 좌·우 스크롤 동기화
        self._left.verticalScrollBar().valueChanged.connect(
            self._right.verticalScrollBar().setValue
        )
        self._right.verticalScrollBar().valueChanged.connect(
            self._left.verticalScrollBar().setValue
        )

        left_panel = self._make_panel(left_label, self._left)
        right_panel = self._make_panel(right_label, self._right)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(left_panel)
        layout.addWidget(right_panel)

    # ── 외부 API ────────────────────────────────────────────────────────────

    def set_texts(self, left: str, right: str) -> None:
        """두 본문 비교 표시 + 라인 단위 하이라이트."""
        self._left.setPlainText(left)
        self._right.setPlainText(right)
        self._highlight(left.splitlines(), right.splitlines())

    # ── 내부 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _make_panel(label: str, editor: QPlainTextEdit) -> QWidget:
        panel = QWidget()
        title = QLabel(label)
        title.setStyleSheet(
            "font-family: 'JetBrains Mono', monospace; "
            "font-size: 11px; letter-spacing: 0.08em; "
            "text-transform: uppercase; color: #7a756c; padding: 4px 0;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(title)
        layout.addWidget(editor)
        return panel

    def _highlight(self, left_lines: list[str], right_lines: list[str]) -> None:
        """``difflib.SequenceMatcher`` 기반 라인 단위 하이라이트."""
        matcher = difflib.SequenceMatcher(a=left_lines, b=right_lines, autojunk=False)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue
            if tag in ("delete", "replace"):
                self._highlight_lines(self._left, i1, i2, _DELETE_BG if tag == "delete" else _REPLACE_BG)
            if tag in ("insert", "replace"):
                self._highlight_lines(
                    self._right, j1, j2, _INSERT_BG if tag == "insert" else _REPLACE_BG
                )

    @staticmethod
    def _highlight_lines(
        editor: QPlainTextEdit, start: int, end: int, bg: QColor
    ) -> None:
        fmt = QTextCharFormat()
        fmt.setBackground(bg)
        doc = editor.document()
        for line_num in range(start, end):
            block = doc.findBlockByLineNumber(line_num)
            if not block.isValid():
                continue
            cursor = QTextCursor(block)
            cursor.select(QTextCursor.SelectionType.LineUnderCursor)
            cursor.mergeCharFormat(fmt)
