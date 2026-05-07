"""MainWindow — 좌 PipelineList / 우 PipelineDetail.

P2 — 시리즈 생성 + 목록·상세 연결. 단계별 액션은 P3+.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QMainWindow,
    QSplitter,
    QStatusBar,
    QWidget,
)

from blogitem.pipeline.service import PipelineService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from blogitem.config import Settings


class MainWindow(QMainWindow):
    """blogitem 메인 윈도우."""

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
        self._service = PipelineService(session_factory)

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
        new_series.triggered.connect(self._open_new_series)
        file_menu.addAction(new_series)

        refresh = QAction("새로고침", self)
        refresh.setShortcut("F5")
        refresh.triggered.connect(self._refresh_list)
        file_menu.addAction(refresh)

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
        from blogitem.ui.pipeline_detail import PipelineDetailWidget
        from blogitem.ui.pipeline_list import PipelineListWidget

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        self._list_widget = PipelineListWidget(service=self._service, parent=splitter)
        self._detail_widget = PipelineDetailWidget(service=self._service, parent=splitter)
        self._list_widget.pipeline_selected.connect(self._detail_widget.show_pipeline)

        splitter.addWidget(self._list_widget)
        splitter.addWidget(self._detail_widget)
        splitter.setSizes([340, 760])

        self.setCentralWidget(splitter)

    # ── 상태바 ──────────────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        from PySide6.QtWidgets import QLabel

        bar = QStatusBar(self)
        dry_run_label = QLabel(
            f"dry_run: {'ON' if self._settings.dry_run else 'OFF'}"
        )
        dry_run_label.setStyleSheet(
            "padding: 0 8px; "
            f"color: {'#c4623c' if self._settings.dry_run else '#063'};"
        )
        bar.addPermanentWidget(dry_run_label)
        bar.addPermanentWidget(QLabel("큐: – · 토큰: –"))
        self.setStatusBar(bar)
        bar.showMessage("준비됨", 3000)

    # ── 액션 ────────────────────────────────────────────────────────────────

    def _open_new_series(self) -> None:
        from blogitem.ui.new_series_dialog import NewSeriesDialog

        dlg = NewSeriesDialog(service=self._service, parent=self)
        if dlg.exec() == NewSeriesDialog.DialogCode.Accepted and dlg.created is not None:
            created = dlg.created
            self._refresh_list()
            self.statusBar().showMessage(
                f"시리즈 #{created.id} 생성 — {created.pipeline_count}개 파이프라인",
                5000,
            )

    def _refresh_list(self) -> None:
        self._list_widget.refresh()

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
