"""ImageImportDialog — 워치 폴더의 최근 이미지를 썸네일로 보여주고 다중 선택 임포트.

UX:
    · 썸네일 그리드 — 200x200 미리보기, 파일명 + 크기 + 수정시각.
    · 체크박스 다중 선택 + 전체 선택/해제 + 새로고침.
    · 선택한 N개 임포트 → ``service.ingest_image()`` 반복 호출.
    · 클립보드에 이미지가 있으면 1번 슬롯에 자동 노출 (Ctrl+V 효과).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    pass


_THUMB_SIZE = 200


class _ImageCard(QFrame):
    """단일 이미지 썸네일 + 체크박스 + 메타."""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { border: 1px solid #d9d0bc; border-radius: 4px; "
            "padding: 6px; background: #fff; }"
            "QFrame[selected='true'] { border-color: #c4623c; background: #fcf0e9; }"
        )

        # 썸네일
        thumb = QLabel()
        thumb.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet("background: #f3efe5;")
        try:
            img = QImage(str(path))
            if not img.isNull():
                pm = QPixmap.fromImage(img).scaled(
                    _THUMB_SIZE,
                    _THUMB_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                thumb.setPixmap(pm)
            else:
                thumb.setText("(이미지 로드 실패)")
        except Exception:  # noqa: BLE001
            thumb.setText("(읽기 오류)")

        # 메타
        try:
            stat = path.stat()
            size_kb = stat.st_size / 1024
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%H:%M:%S")
            meta_text = f"{size_kb:,.0f} KB · {mtime}"
        except OSError:
            meta_text = "(메타 읽기 실패)"

        name_lbl = QLabel(path.name)
        name_lbl.setStyleSheet("font-size: 11px; font-weight: 600;")
        name_lbl.setWordWrap(True)
        meta_lbl = QLabel(meta_text)
        meta_lbl.setStyleSheet("color: #7a756c; font-size: 10px;")

        self.checkbox = QCheckBox("선택")
        self.checkbox.toggled.connect(self._on_toggle)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(thumb)
        layout.addWidget(name_lbl)
        layout.addWidget(meta_lbl)
        layout.addWidget(self.checkbox)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, checked: bool) -> None:
        self.checkbox.setChecked(checked)

    def _on_toggle(self, checked: bool) -> None:
        self.setProperty("selected", checked)
        self.style().unpolish(self)
        self.style().polish(self)


class ImageImportDialog(QDialog):
    """썸네일 그리드 임포트 다이얼로그.

    Signals:
        refresh_requested(): 사용자가 새로고침 클릭 (외부에서 새 목록을 set_paths 로 주입).
    """

    refresh_requested = Signal()

    def __init__(
        self,
        *,
        watch_dir: Path,
        initial_paths: list[Path] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"이미지 임포트 — {watch_dir}")
        self.setMinimumSize(900, 640)
        self._cards: list[_ImageCard] = []
        self._selected: list[Path] = []

        # 헤더
        header = QHBoxLayout()
        self._summary = QLabel("(이미지 검색 중…)")
        self._summary.setStyleSheet("color: #4a4742;")
        header.addWidget(self._summary, stretch=1)

        select_all_btn = QPushButton("전체 선택")
        select_all_btn.clicked.connect(lambda: self._select_all(True))
        deselect_all_btn = QPushButton("전체 해제")
        deselect_all_btn.clicked.connect(lambda: self._select_all(False))
        refresh_btn = QPushButton("🔄 새로고침")
        refresh_btn.clicked.connect(self.refresh_requested.emit)
        for b in (select_all_btn, deselect_all_btn, refresh_btn):
            header.addWidget(b)

        # 썸네일 그리드 (스크롤 가능)
        self._grid_container = QWidget()
        self._grid_layout = QGridLayout(self._grid_container)
        self._grid_layout.setContentsMargins(4, 4, 4, 4)
        self._grid_layout.setSpacing(8)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._grid_container)

        # 버튼
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("선택 임포트")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(buttons)

        if initial_paths is not None:
            self.set_paths(initial_paths)

    # ── 외부 API ────────────────────────────────────────────────────────────

    def set_paths(self, paths: list[Path]) -> None:
        """후보 이미지 목록 갱신. 기존 카드 제거 후 새로 그림."""
        # 기존 카드 정리
        for card in self._cards:
            self._grid_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

        # 그리드에 새 카드 채우기 — 4열
        cols = 4
        for i, path in enumerate(paths):
            card = _ImageCard(path, parent=self._grid_container)
            self._cards.append(card)
            self._grid_layout.addWidget(card, i // cols, i % cols)

        if paths:
            self._summary.setText(f"{len(paths)}개 이미지 발견 — 임포트할 파일 선택")
        else:
            self._summary.setText("최근 이미지가 없습니다 — 새로고침 또는 다른 폴더 사용")

    @property
    def selected_paths(self) -> list[Path]:
        return list(self._selected)

    # ── 내부 ────────────────────────────────────────────────────────────────

    def _select_all(self, checked: bool) -> None:
        for card in self._cards:
            card.set_checked(checked)

    def _on_accept(self) -> None:
        self._selected = [c.path for c in self._cards if c.is_checked()]
        if not self._selected:
            self._summary.setText("⚠ 임포트할 이미지를 1개 이상 선택하세요.")
            self._summary.setStyleSheet("color: #c4623c; font-weight: 600;")
            return
        self.accept()
