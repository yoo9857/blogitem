"""ArtifactViewerDialog — 산출물 풀 뷰어 (텍스트/JSON/이미지).

산출물 카드/썸네일 클릭 시 호출. 단순 + 빠름:
    · 텍스트/JSON: monospace QPlainTextEdit (편집 불가) + 파일 정보 + 검색
    · 이미지: QLabel + QPixmap (스케일 fit-to-window)
    · 메타: 경로 / 크기 / sha256 / 시각
    · 액션: [폴더에서 보기] (탐색기 열기), [닫기]
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from blogitem.pipeline.dto import ArtifactSummary


class ArtifactViewerDialog(QDialog):
    """산출물 1개 뷰어. 종류별로 다른 위젯 표시."""

    def __init__(
        self,
        *,
        artifact: ArtifactSummary,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._artifact = artifact
        title = f"{artifact.stage.value} · {artifact.kind} · {artifact.abs_path.name}"
        self.setWindowTitle(title)
        self.setMinimumSize(820, 620)

        # 메타 헤더
        meta_row = QHBoxLayout()
        meta_text = (
            f"<b>경로:</b> <code>{artifact.rel_path}</code>  ·  "
            f"<b>크기:</b> {artifact.size:,} bytes  ·  "
            f"<b>sha:</b> <code>{artifact.sha256[:12]}…</code>  ·  "
            f"<b>시각:</b> {artifact.created_at.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        meta_lbl = QLabel(meta_text)
        meta_lbl.setStyleSheet(
            "padding: 6px 10px; background: #ebe4d2; color: #4a4742; "
            "font-size: 11px; border-radius: 3px;"
        )
        meta_lbl.setTextFormat(Qt.TextFormat.RichText)
        meta_lbl.setWordWrap(True)
        meta_row.addWidget(meta_lbl, stretch=1)

        open_folder_btn = QPushButton("📁 폴더 열기")
        open_folder_btn.clicked.connect(self._open_folder)
        meta_row.addWidget(open_folder_btn)

        # 본문 — 종류별
        body = self._build_body()

        # 닫기
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addLayout(meta_row)
        layout.addWidget(body, stretch=1)
        layout.addWidget(buttons)

    # ── 본문 분기 ───────────────────────────────────────────────────────────

    def _build_body(self) -> QWidget:
        if self._artifact.kind == "image":
            return self._build_image_view()
        return self._build_text_view()

    def _build_text_view(self) -> QWidget:
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        editor.setStyleSheet(
            "QPlainTextEdit { font-family: 'JetBrains Mono', Consolas, monospace; "
            "font-size: 12px; background: #fcfaf3; border: 1px solid #d9d0bc; }"
        )
        try:
            text = self._artifact.abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            text = f"(파일 로드 실패: {type(e).__name__}: {e})"
        editor.setPlainText(text)
        return editor

    def _build_image_view(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background: #f3efe5; border: 1px solid #d9d0bc; }"
        )

        label = QLabel()
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            pm = QPixmap(str(self._artifact.abs_path))
            if not pm.isNull():
                # 화면에 맞춰 축소 (원본보다 크게는 X)
                max_w = 1200
                if pm.width() > max_w:
                    pm = pm.scaledToWidth(
                        max_w, Qt.TransformationMode.SmoothTransformation
                    )
                label.setPixmap(pm)
            else:
                label.setText("(이미지 로드 실패)")
        except Exception as e:  # noqa: BLE001
            label.setText(f"(이미지 오류: {e})")

        scroll.setWidget(label)
        return scroll

    # ── 액션 ────────────────────────────────────────────────────────────────

    def _open_folder(self) -> None:
        """OS 파일 탐색기에서 부모 폴더 열기."""
        path = self._artifact.abs_path
        try:
            if sys.platform == "win32":
                # explorer /select 로 파일 강조
                subprocess.run(
                    ["explorer", "/select,", str(path)],
                    check=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path.parent)], check=False)
        except OSError:
            pass

    @staticmethod
    def _safe_open_path(path: str) -> bool:
        """경로 검증 — 절대경로만 허용 (path traversal 방어)."""
        return os.path.isabs(path)
