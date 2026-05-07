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

        view_menu = bar.addMenu("&보기")
        toggle_terminal = QAction("터미널 표시/숨김", self)
        toggle_terminal.setShortcut("Ctrl+`")
        toggle_terminal.setCheckable(True)
        toggle_terminal.setChecked(True)
        toggle_terminal.triggered.connect(self._toggle_terminal)
        view_menu.addAction(toggle_terminal)
        self._toggle_terminal_action = toggle_terminal

        help_menu = bar.addMenu("&도움말")
        about_action = QAction("blogitem 정보", self)
        about_action.triggered.connect(self._open_about)
        help_menu.addAction(about_action)

    # ── 본문 ────────────────────────────────────────────────────────────────

    def _build_central(self) -> None:
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QDockWidget

        from blogitem.ui.pipeline_detail import PipelineDetailWidget
        from blogitem.ui.pipeline_list import PipelineListWidget
        from blogitem.ui.terminal_panel import TerminalPanel

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

        # ── 하단 도크: 터미널 패널 (CLI 스트리밍 + ad-hoc 프롬프트) ───────────
        self._terminal = TerminalPanel(settings=self._settings, parent=self)
        self._terminal_dock = QDockWidget("Terminal", self)
        self._terminal_dock.setObjectName("TerminalDock")
        self._terminal_dock.setWidget(self._terminal)
        self._terminal_dock.setAllowedAreas(_Qt.DockWidgetArea.BottomDockWidgetArea)
        self.addDockWidget(_Qt.DockWidgetArea.BottomDockWidgetArea, self._terminal_dock)
        self.resizeDocks([self._terminal_dock], [220], _Qt.Orientation.Vertical)

        # 자동 단계 워커 출력 → 터미널 패널 스트리밍
        self._detail_widget.output_line.connect(
            lambda line: self._terminal.append_line(line, kind="stdout")
        )

        # ad-hoc 입력 → PromptWorker
        self._terminal.prompt_submitted.connect(self._run_terminal_prompt)
        self._prompt_worker = None  # type: ignore[var-annotated]

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
        from blogitem.pipeline.orchestrator import make_orchestrator_service
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

        # Orchestrator (자동 advance loop) — 사용자가 enable 한 경우만 동작
        self._orchestrator = make_orchestrator_service(
            service=self._service,
            settings=self._settings,
            parent=self,
        )
        self._orchestrator.pipeline_started.connect(self._on_orchestrator_started)
        self._orchestrator.pipeline_advanced.connect(self._on_orchestrator_advanced)
        self._orchestrator.pipeline_failed.connect(self._on_orchestrator_failed)
        self._orchestrator.output_line.connect(
            lambda line: self._terminal.append_line(line, kind="stdout")
        )
        if self._settings.orchestrator_enabled:
            self._orchestrator.start()
            self._terminal.append_line(
                "(Orchestrator 활성 — PENDING 자동 단계 자동 진행)", kind="info"
            )

    def _on_orchestrator_started(self, pipeline_id: int, stage: str) -> None:
        self._terminal.append_turn_separator(
            label=f"orchestrator · #{pipeline_id} {stage}"
        )
        self._terminal.append_line(
            f"🤖 #{pipeline_id} {stage} 단계 자동 시작…", kind="info"
        )

    def _on_orchestrator_advanced(self, pipeline_id: int, stage: str) -> None:
        self._terminal.append_line(
            f"✓ #{pipeline_id} → {stage}", kind="assistant"
        )
        self._list_widget.refresh()
        if self._detail_widget._current_id == pipeline_id:
            self._detail_widget.show_pipeline(pipeline_id)

    def _on_orchestrator_failed(self, pipeline_id: int, message: str) -> None:
        self._terminal.append_line(
            f"⚠ #{pipeline_id} 자동 실행 실패: {message}", kind="error"
        )
        self._list_widget.refresh()

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

    def _toggle_terminal(self, checked: bool) -> None:
        if hasattr(self, "_terminal_dock"):
            self._terminal_dock.setVisible(checked)

    # ── 터미널 ad-hoc 프롬프트 ──────────────────────────────────────────────

    def _run_terminal_prompt(self, prompt: str) -> None:
        from blogitem.ui.workers.prompt_worker import PromptWorker

        if self._prompt_worker is not None and self._prompt_worker.isRunning():
            self._terminal.append_line(
                "(이전 호출이 아직 진행 중 — 잠시 후 다시 시도)", kind="error"
            )
            return

        self._terminal.set_busy(True)
        self._prompt_worker = PromptWorker(
            prompt=prompt, settings=self._settings, parent=self
        )
        self._prompt_worker.line_received.connect(
            lambda line: self._terminal.append_line(line, kind="stdout")
        )
        self._prompt_worker.finished_ok.connect(self._on_prompt_ok)
        self._prompt_worker.failed.connect(self._on_prompt_fail)
        self._prompt_worker.finished.connect(lambda: self._terminal.set_busy(False))
        self._prompt_worker.start()

    def _on_prompt_ok(self, response: str) -> None:
        self._terminal.append_line("(완료)", kind="info")
        self._terminal.update_status(message="last call: ok")

    def _on_prompt_fail(self, message: str) -> None:
        self._terminal.append_line(message, kind="error")
        self._terminal.update_status(message="last call: failed")

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
        for service_attr in ("_orchestrator", "_watchdog"):
            svc = getattr(self, service_attr, None)
            if svc is not None:
                try:
                    svc.stop()
                except Exception:  # noqa: BLE001
                    pass
        super().closeEvent(event)  # type: ignore[arg-type]
