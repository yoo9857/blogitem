"""ArtifactViewerDialog — 산출물 풀 뷰어 (텍스트/JSON/이미지).

산출물 카드/썸네일 클릭 시 호출. 단순 + 빠름:
    · 텍스트/JSON: monospace QPlainTextEdit (편집 불가) + 파일 정보 + 검색
    · 이미지: QLabel + QPixmap (스케일 fit-to-window)
    · 메타: 경로 / 크기 / sha256 / 시각
    · 액션: [폴더에서 보기] (탐색기 열기), [닫기]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
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

        # 텍스트/JSON — 커리큘럼이면 정돈된 뷰 + 원본 토글
        try:
            text = self._artifact.abs_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return self._build_raw_text_view(
                f"(파일 로드 실패: {type(e).__name__}: {e})"
            )

        curriculum = self._parse_curriculum(text)
        if curriculum is not None:
            return self._build_curriculum_view(curriculum, raw_text=text)
        return self._build_raw_text_view(text)

    @staticmethod
    def _parse_curriculum(text: str) -> dict | None:
        """``{series_title, lectures: [...]}`` 형태면 반환, 아니면 None."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        if "series_title" not in data and "lectures" not in data:
            return None
        if not isinstance(data.get("lectures"), list):
            return None
        return data

    def _build_curriculum_view(
        self, curriculum: dict, *, raw_text: str
    ) -> QWidget:
        """커리큘럼 정돈 뷰 — 시리즈 헤더 + 강의 카드 N개. 원본 JSON 토글."""
        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        # 토글 바 — "📋 정돈된 보기" / "</> 원본 JSON"
        toggle_row = QHBoxLayout()
        toggle_btn = QPushButton("</> 원본 JSON")
        toggle_btn.setCheckable(True)
        toggle_btn.setStyleSheet(
            "QPushButton { padding: 4px 12px; font-size: 11px; "
            "background: transparent; border: 1px solid #d9d0bc; border-radius: 3px; }"
            "QPushButton:checked { background: #ebe4d2; color: #c4623c; border-color: #c4623c; }"
        )
        toggle_row.addStretch(1)
        toggle_row.addWidget(toggle_btn)

        # 스택 — 0: formatted, 1: raw
        stack = QStackedWidget()
        stack.addWidget(self._build_curriculum_cards(curriculum))
        stack.addWidget(self._build_raw_text_view(raw_text))
        toggle_btn.toggled.connect(
            lambda checked: stack.setCurrentIndex(1 if checked else 0)
        )

        outer.addLayout(toggle_row)
        outer.addWidget(stack, stretch=1)
        return wrapper

    def _build_curriculum_cards(self, curriculum: dict) -> QWidget:
        series_title = str(curriculum.get("series_title") or "").strip()
        series_intro = str(curriculum.get("series_intro") or "").strip()
        lectures = curriculum.get("lectures") or []

        container = QWidget()
        col = QVBoxLayout(container)
        col.setContentsMargins(2, 2, 2, 2)
        col.setSpacing(10)

        # 시리즈 헤더
        if series_title or series_intro:
            header = QFrame()
            header.setStyleSheet(
                "QFrame { background: #ebe4d2; border-radius: 4px; padding: 12px; }"
            )
            h_layout = QVBoxLayout(header)
            h_layout.setContentsMargins(12, 10, 12, 10)
            h_layout.setSpacing(6)
            if series_title:
                t = QLabel(f"📚 {escape(series_title)}")
                t.setStyleSheet(
                    "font-size: 16px; font-weight: 700; color: #0a0908;"
                )
                t.setWordWrap(True)
                h_layout.addWidget(t)
            if series_intro:
                i = QLabel(escape(series_intro))
                i.setStyleSheet("color: #4a4742; font-size: 12px;")
                i.setWordWrap(True)
                h_layout.addWidget(i)
            meta = QLabel(f"강의 수: <b>{len(lectures)}강</b>")
            meta.setTextFormat(Qt.TextFormat.RichText)
            meta.setStyleSheet("color: #7a756c; font-size: 11px;")
            h_layout.addWidget(meta)
            col.addWidget(header)

        # 강의 카드
        for lec in lectures:
            if not isinstance(lec, dict):
                continue
            col.addWidget(self._build_lecture_card(lec))

        col.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        scroll.setStyleSheet("QScrollArea { border: none; background: #fcfaf3; }")
        return scroll

    @staticmethod
    def _build_lecture_card(lec: dict) -> QFrame:
        position = lec.get("position") or "?"
        title = str(lec.get("title") or "").strip()
        summary = str(lec.get("summary") or "").strip()
        outcomes = lec.get("learning_outcomes") or []
        concepts = lec.get("key_concepts") or []
        reading = lec.get("estimated_reading_min")

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #fff; border: 1px solid #d9d0bc; "
            "border-radius: 4px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        # 헤더 — N강 · 제목 · 읽기시간
        head_row = QHBoxLayout()
        pos_lbl = QLabel(f"<span style='color:#c4623c;'>{position}강</span>")
        pos_lbl.setTextFormat(Qt.TextFormat.RichText)
        pos_lbl.setStyleSheet("font-weight: 700; font-size: 13px;")
        head_row.addWidget(pos_lbl)
        title_lbl = QLabel(escape(title))
        title_lbl.setStyleSheet("font-weight: 700; font-size: 13px; color: #0a0908;")
        title_lbl.setWordWrap(True)
        head_row.addWidget(title_lbl, stretch=1)
        if isinstance(reading, (int, float)) and reading:
            rt = QLabel(f"⏱ {int(reading)}분")
            rt.setStyleSheet("color: #7a756c; font-size: 11px;")
            head_row.addWidget(rt)
        layout.addLayout(head_row)

        # 요약
        if summary:
            s = QLabel(escape(summary))
            s.setStyleSheet("color: #4a4742; font-size: 12px;")
            s.setWordWrap(True)
            layout.addWidget(s)

        # 학습 결과
        if isinstance(outcomes, list) and outcomes:
            ol = QLabel(
                "<b style='color:#0a0908;font-size:11px;'>학습 결과</b><br>"
                + "<br>".join(
                    f"<span style='color:#4a4742;'>• {escape(str(o))}</span>"
                    for o in outcomes
                    if o
                )
            )
            ol.setTextFormat(Qt.TextFormat.RichText)
            ol.setWordWrap(True)
            ol.setStyleSheet("font-size: 12px; padding-top: 4px;")
            layout.addWidget(ol)

        # 핵심 개념 — chip 스타일
        if isinstance(concepts, list) and concepts:
            chips_row = QHBoxLayout()
            chips_row.setSpacing(6)
            chips_row.setContentsMargins(0, 4, 0, 0)
            label = QLabel("핵심 개념:")
            label.setStyleSheet("color: #7a756c; font-size: 11px;")
            chips_row.addWidget(label)
            for c in concepts:
                chip = QLabel(escape(str(c)))
                chip.setStyleSheet(
                    "QLabel { background: #f3efe5; color: #4a4742; "
                    "border: 1px solid #d9d0bc; border-radius: 10px; "
                    "padding: 2px 8px; font-size: 11px; }"
                )
                chips_row.addWidget(chip)
            chips_row.addStretch(1)
            wrapper = QWidget()
            wrapper.setLayout(chips_row)
            layout.addWidget(wrapper)

        return card

    def _build_raw_text_view(self, text: str) -> QWidget:
        # JSON 이면 들여쓰기로 가독성 향상 — 실패 시 원본 그대로
        try:
            parsed = json.loads(text)
            text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            pass

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        editor.setStyleSheet(
            "QPlainTextEdit { font-family: 'JetBrains Mono', Consolas, monospace; "
            "font-size: 12px; background: #fcfaf3; border: 1px solid #d9d0bc; }"
        )
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
