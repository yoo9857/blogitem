"""업로드 다이얼로그 — 이미지 다중 + 인간화 텍스트.

이미지: 드래그앤드롭 + 파일 선택. PNG/JPG/JPEG/WebP/GIF/BMP 만 허용 (ArtifactStore
가 거절). 다중 선택 가능.

텍스트: 클립보드 붙여넣기 또는 파일 드롭 또는 직접 입력. ChatGPT 웹에서 받은
인간화 본문(Markdown) 을 그대로 붙여넣는 시나리오.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    pass


_ACCEPTED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20MB


# ─── 이미지 다중 업로드 ─────────────────────────────────────────────────────────


class _DropArea(QFrame):
    """이미지 드래그앤드롭 영역."""

    files_dropped = Signal(list)  # list[Path]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumHeight(140)
        self.setStyleSheet(
            "QFrame { border: 2px dashed #d9d0bc; border-radius: 6px; "
            "background: #fcfaf3; }"
            "QFrame[active='true'] { border-color: #c4623c; background: #fcf0e9; }"
        )
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._label = QLabel(
            "이미지 파일을 여기에 드래그하거나 [파일 선택] 버튼을 사용하세요.\n"
            "PNG / JPG / WebP / GIF / BMP — 최대 20MB"
        )
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("color: #7a756c; border: none; background: transparent;")
        layout.addWidget(self._label)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setProperty("active", True)
            self.style().unpolish(self)
            self.style().polish(self)
        else:
            event.ignore()

    def dragLeaveEvent(self, event: object) -> None:  # noqa: N802
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self.setProperty("active", False)
        self.style().unpolish(self)
        self.style().polish(self)

        urls = event.mimeData().urls()
        paths: list[Path] = []
        for url in urls:
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        if paths:
            self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class ImageUploadDialog(QDialog):
    """이미지 다중 업로드 다이얼로그.

    ``selected_paths`` 프로퍼티로 검증 통과한 경로 리스트 반환.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("이미지 업로드")
        self.setMinimumSize(560, 460)

        self._paths: list[Path] = []

        layout = QVBoxLayout(self)

        drop_area = _DropArea(self)
        drop_area.files_dropped.connect(self._add_paths)
        layout.addWidget(drop_area)

        pick_btn = QPushButton("파일 선택…", self)
        pick_btn.clicked.connect(self._open_file_picker)
        layout.addWidget(pick_btn)

        self._list = QListWidget(self)
        layout.addWidget(self._list)

        remove_btn = QPushButton("선택 항목 삭제", self)
        remove_btn.clicked.connect(self._remove_selected)
        layout.addWidget(remove_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── 외부 API ────────────────────────────────────────────────────────────

    @property
    def selected_paths(self) -> list[Path]:
        return list(self._paths)

    # ── 내부 ────────────────────────────────────────────────────────────────

    def _open_file_picker(self) -> None:
        paths_str, _ = QFileDialog.getOpenFileNames(
            self,
            "이미지 선택",
            "",
            "이미지 (*.png *.jpg *.jpeg *.webp *.gif *.bmp)",
        )
        if paths_str:
            self._add_paths([Path(p) for p in paths_str])

    def _add_paths(self, paths: list[Path]) -> None:
        invalid: list[str] = []
        for p in paths:
            try:
                self._validate_image(p)
            except ValueError as e:
                invalid.append(f"{p.name}: {e}")
                continue
            if p in self._paths:
                continue
            self._paths.append(p)
            QListWidgetItem(str(p), self._list)

        if invalid:
            QMessageBox.warning(
                self,
                "일부 파일이 거부됨",
                "다음 파일들이 추가되지 않았습니다:\n\n" + "\n".join(invalid),
            )

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            row = self._list.row(item)
            self._list.takeItem(row)
            del self._paths[row]

    @staticmethod
    def _validate_image(path: Path) -> None:
        if not path.is_file():
            raise ValueError("파일이 존재하지 않음")
        ext = path.suffix.lower()
        if ext not in _ACCEPTED_IMAGE_EXT:
            raise ValueError(f"지원 안 하는 형식: {ext}")
        size = path.stat().st_size
        if size == 0:
            raise ValueError("빈 파일")
        if size > _MAX_IMAGE_BYTES:
            raise ValueError(
                f"크기 초과 ({size / 1024 / 1024:.1f}MB > "
                f"{_MAX_IMAGE_BYTES / 1024 / 1024:.0f}MB)"
            )


# ─── 인간화 텍스트 입력 ────────────────────────────────────────────────────────


class TextUploadDialog(QDialog):
    """4단계 인간화 본문 입력 다이얼로그.

    ChatGPT 웹에서 복사한 Markdown 을 붙여넣는 시나리오.
    파일 드롭으로 .md / .txt 도 지원.
    """

    def __init__(
        self,
        *,
        title: str = "인간화 본문 업로드",
        placeholder: str = "ChatGPT 웹에서 복사한 Markdown 본문을 여기에 붙여넣으세요…",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(720, 540)

        self._editor = QPlainTextEdit(self)
        self._editor.setPlaceholderText(placeholder)
        self._editor.setAcceptDrops(True)
        self._editor.installEventFilter(self)  # 파일 드롭은 별도 처리

        info = QLabel("파일 드롭(.md / .txt)도 지원. 200~10,000자 권장.")
        info.setStyleSheet("color: #7a756c; font-size: 11px;")

        button_row = QHBoxLayout()
        load_btn = QPushButton("파일에서 불러오기…", self)
        load_btn.clicked.connect(self._load_from_file)
        clear_btn = QPushButton("지우기", self)
        clear_btn.clicked.connect(self._editor.clear)
        button_row.addWidget(load_btn)
        button_row.addWidget(clear_btn)
        button_row.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self._editor)
        layout.addWidget(info)
        layout.addLayout(button_row)
        layout.addWidget(buttons)

    # ── 외부 API ────────────────────────────────────────────────────────────

    @property
    def text(self) -> str:
        return self._editor.toPlainText()

    def set_text(self, text: str) -> None:
        self._editor.setPlainText(text)

    # ── 내부 ────────────────────────────────────────────────────────────────

    def _load_from_file(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "본문 파일 선택",
            "",
            "텍스트 (*.md *.txt *.markdown)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            QMessageBox.critical(self, "읽기 실패", f"{type(e).__name__}: {e}")
            return
        self._editor.setPlainText(content)

    def _on_accept(self) -> None:
        if not self._editor.toPlainText().strip():
            QMessageBox.warning(self, "검증 실패", "본문이 비어있습니다.")
            return
        self.accept()
