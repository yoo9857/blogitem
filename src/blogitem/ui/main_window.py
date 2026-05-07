"""MainWindow — 좌 PipelineList / 우 PipelineDetail + Watchdog + 알림.

P5 통합 — WatchdogService 가 1시간 간격으로 정체/토큰 만료 감지 →
상태바 갱신 + 데스크톱 알림.
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
    QWidget,
)

from blogitem.pipeline.service import PipelineService

if TYPE_CHECKING:
    from sqlalchemy.orm import Session, sessionmaker

    from blogitem.config import Settings
    from blogitem.watchdog.monitor import StuckPipeline


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
        self._start_watchdog()

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
        self._detail_widget = PipelineDetailWidget(
            service=self._service, settings=self._settings, parent=splitter
        )
        self._list_widget.pipeline_selected.connect(self._detail_widget.show_pipeline)
        self._detail_widget.pipeline_changed.connect(
            lambda _id: self._list_widget.refresh()
        )

        splitter.addWidget(self._list_widget)
        splitter.addWidget(self._detail_widget)
        splitter.setSizes([340, 760])

        self.setCentralWidget(splitter)

    # ── 상태바 ──────────────────────────────────────────────────────────────

    def _build_status_bar(self) -> None:
        bar = QStatusBar(self)

        self._dry_run_label = QLabel(
            f"dry_run: {'ON' if self._settings.dry_run else 'OFF'}"
        )
        self._dry_run_label.setStyleSheet(
            "padding: 0 8px; "
            f"color: {'#c4623c' if self._settings.dry_run else '#063'};"
        )
        bar.addPermanentWidget(self._dry_run_label)

        self._queue_label = QLabel("큐: – ")
        self._token_label = QLabel("토큰: – ")
        bar.addPermanentWidget(self._queue_label)
        bar.addPermanentWidget(self._token_label)

        self.setStatusBar(bar)
        bar.showMessage("준비됨", 3000)

    # ── Watchdog ────────────────────────────────────────────────────────────

    def _start_watchdog(self) -> None:
        from blogitem.naver.token_store import TokenStore
        from blogitem.notify.notifier import Notifier
        from blogitem.watchdog.monitor import make_watchdog_service

        self._notifier = Notifier()
        self._watchdog = make_watchdog_service(
            session_factory=self._session_factory,
            token_store=TokenStore(),
            parent=self,
        )
        self._watchdog.stuck_found.connect(self._on_stuck_found)
        self._watchdog.token_expiring.connect(self._on_token_expiring)
        self._watchdog.queue_summary.connect(self._on_queue_summary)
        self._watchdog.start(interval_min=60)

    def _on_stuck_found(self, stuck_list: list[StuckPipeline]) -> None:
        if not stuck_list:
            return
        n = len(stuck_list)
        self._notifier.desktop(
            title="blogitem · 정체 감지",
            message=f"{n} 개 파이프라인이 24시간 이상 진행되지 않았습니다.",
        )
        self.statusBar().showMessage(
            f"⚠ {n} 개 파이프라인 정체됨 — 좌측 목록 확인", 10000
        )

    def _on_token_expiring(self, days: int) -> None:
        self._notifier.desktop(
            title="blogitem · 네이버 토큰 만료 임박",
            message=f"refresh_token 만료까지 {days}일 — [설정] 에서 재인증 권장.",
        )
        self._token_label.setText(f"토큰: {days}일")
        self._token_label.setStyleSheet(
            f"padding: 0 8px; color: {'#c4623c' if days <= 7 else '#7a756c'};"
        )

    def _on_queue_summary(self, counts: dict[str, int]) -> None:
        pending = counts.get("pending", 0) + counts.get("running", 0)
        awaiting = counts.get("awaiting_input", 0) + counts.get("awaiting_review", 0)
        failed = counts.get("failed", 0)
        text = f"큐: 진행 {pending} · 대기 {awaiting} · 실패 {failed}"
        if failed > 0:
            self._queue_label.setStyleSheet("padding: 0 8px; color: #c4623c;")
        else:
            self._queue_label.setStyleSheet("padding: 0 8px; color: #4a4742;")
        self._queue_label.setText(text)

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

    # ── 종료 처리 ───────────────────────────────────────────────────────────

    def closeEvent(self, event: object) -> None:  # noqa: N802
        if hasattr(self, "_watchdog"):
            try:
                self._watchdog.stop()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(event)  # type: ignore[arg-type]
