"""MainWindow — 좌측 파이프라인 목록 / 우측 단계별 상세.

P0 — 골격만 (Splitter + StatusBar + 메뉴). 실제 파이프라인 위젯은 P2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from blogitem.config import Settings


class MainWindow(QMainWindow):
    """blogitem 메인 윈도우.

    레이아웃:
        ``QSplitter(Horizontal)``
          ├ 좌: PipelineList (P2)
          └ 우: PipelineDetail (P2)
        ``QStatusBar`` — dry_run / 큐 상태 / 토큰 만료 일수 (P5).
    """

    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._session_factory = session_factory

        self.setWindowTitle("blogitem")
        self.resize(1100, 720)

        self._build_menu()
        self._build_central()
        self._build_status_bar()

    # ── 메뉴 ────────────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&파일")

        new_series = QAction("새 시리즈…", self)
        new_series.setShortcut(QKeySequence.StandardKey.New)
        new_series.setStatusTip("새 강의/시리즈 생성 (P2 — 구현 예정)")
        new_series.setEnabled(False)
        file_menu.addAction(new_series)

        file_menu.addSeparator()

        quit_action = QAction("종료", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        settings_menu = bar.addMenu("&설정")
        settings_action = QAction("설정…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings)
        settings_menu.addAction(settings_action)

        help_menu = bar.addMenu("&도움말")
        about_action = QAction("blogitem 정보", self)
        about_action.triggered.connect(self._open_about)
        help_menu.addAction(about_action)

    # ── 본문 ────────────────────────────────────────────────────────────────

    def _build_central(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        # 좌측 — 파이프라인 목록 자리 (P2)
        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 12, 12, 12)
        placeholder_left = QLabel("Pipelines\n\n(P2 — PipelineList 위젯 자리)")
        placeholder_left.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_left.setStyleSheet("color: #888; font-size: 13px;")
        left_layout.addWidget(placeholder_left)

        # 우측 — 파이프라인 상세 자리 (P2)
        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 16, 16, 16)
        placeholder_right = QLabel("Pipeline Detail\n\n(P2 — 단계별 상태 카드 자리)")
        placeholder_right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        placeholder_right.setStyleSheet("color: #888; font-size: 13px;")
        right_layout.addWidget(placeholder_right)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([320, 780])

        self.setCentralWidget(splitter)

    # ── 상태바 ──────────────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        bar = QStatusBar(self)

        dry_run_label = QLabel(
            f"dry_run: {'ON' if self._settings.dry_run else 'OFF'}"
        )
        dry_run_label.setStyleSheet(
            "padding: 0 8px; "
            f"color: {'#c4623c' if self._settings.dry_run else '#063'};"
        )
        bar.addPermanentWidget(dry_run_label)

        # 큐/토큰 메트릭은 P5 에서 채움 (Watchdog 연결).
        bar.addPermanentWidget(QLabel("큐: – · 토큰: –"))

        self.setStatusBar(bar)
        bar.showMessage("준비됨", 3000)

    # ── 액션 ────────────────────────────────────────────────────────────────

    def _open_settings(self) -> None:
        from blogitem.ui.settings_dialog import SettingsDialog

        dlg = SettingsDialog(parent=self)
        dlg.exec()

    def _open_about(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        from blogitem import __version__

        QMessageBox.about(
            self,
            "blogitem",
            f"<h3>blogitem</h3>"
            f"<p>AI 멀티-스텝 콘텐츠 파이프라인 데스크톱 앱.</p>"
            f"<p>버전 {__version__}</p>"
            f"<p><a href='https://github.com/yoo9857/blogitem'>"
            f"github.com/yoo9857/blogitem</a></p>",
        )
