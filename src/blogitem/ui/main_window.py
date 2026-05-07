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

        series_prompts = QAction("🎨 시리즈 이미지 프롬프트", self)
        series_prompts.setShortcut("Ctrl+I")
        series_prompts.setToolTip(
            "시리즈 단위로 이미지 프롬프트 한 번에 생성 — 시리즈 썸네일 1 + 강당 본문 1. "
            "이미 생성됐으면 기존 프롬프트만 표시."
        )
        series_prompts.triggered.connect(self._open_series_image_prompts)
        file_menu.addAction(series_prompts)

        regen_prompts = QAction("🔄 시리즈 이미지 프롬프트 강제 재생성", self)
        regen_prompts.setShortcut("Ctrl+Shift+I")
        regen_prompts.setToolTip(
            "기존 프롬프트를 무시하고 Claude 를 다시 호출. 비용 발생 — 확인 다이얼로그 띄움."
        )
        regen_prompts.triggered.connect(self._force_regen_series_image_prompts)
        file_menu.addAction(regen_prompts)

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

    # ── 시리즈 이미지 프롬프트 ────────────────────────────────────────────────

    def _force_regen_series_image_prompts(self) -> None:
        """기존 산출물 무시하고 강제 재생성 — 사용자 확인 후."""
        from PySide6.QtWidgets import QMessageBox

        pid = self._list_widget.current_pipeline_id()
        if pid is None:
            QMessageBox.information(
                self,
                "재생성",
                "좌측에서 시리즈에 속한 파이프라인을 먼저 선택하세요.",
            )
            return
        dto = self._service.get_pipeline(pid)
        if dto is None or dto.series_id is None:
            QMessageBox.information(
                self, "재생성", "이 파이프라인은 시리즈에 속해있지 않습니다."
            )
            return

        confirm = QMessageBox.question(
            self,
            "강제 재생성",
            "기존 시리즈 이미지 프롬프트를 무시하고 Claude 를 다시 호출합니다.\n"
            "(LLM 호출 비용 발생 — claude_cli 모드면 구독 한도 차감)\n\n"
            "계속하시겠습니까?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._open_series_image_prompts(force=True)

    def _open_series_image_prompts(self, force: bool = False) -> None:
        """좌측에서 선택된 파이프라인의 시리즈에 대해 이미지 프롬프트 다이얼로그.

        - 이미 생성된 경우: 기존 프롬프트 다이얼로그 표시 (재생성 X — "다시 안 됨")
        - 없으면: Claude 호출 → 저장 → 다이얼로그
        """
        from PySide6.QtWidgets import QMessageBox, QProgressDialog

        from blogitem.pipeline.artifacts import ArtifactStore
        from blogitem.ui.image_prompts_dialog import ImagePromptsDialog
        from blogitem.ui.workers.series_image_prompts_worker import (
            SeriesImagePromptsWorker,
        )

        pid = self._list_widget.current_pipeline_id()
        if pid is None:
            QMessageBox.information(
                self,
                "시리즈 이미지 프롬프트",
                "좌측에서 시리즈에 속한 파이프라인을 먼저 선택하세요.",
            )
            return

        dto = self._service.get_pipeline(pid)
        if dto is None or dto.series_id is None:
            QMessageBox.information(
                self,
                "시리즈 이미지 프롬프트",
                "이 파이프라인은 시리즈에 속해있지 않습니다 — 시리즈 단위 생성 불가.",
            )
            return
        series_id = int(dto.series_id)

        # 이미 생성됐으면 다시 호출 안 하고 다이얼로그만 (force 면 스킵)
        if not force and self._service.has_series_image_prompts(series_id):
            store = ArtifactStore(self._settings.artifacts_dir)
            data = self._service.read_series_image_prompts(
                series_id, artifact_store=store
            )
            if data is None:
                QMessageBox.warning(
                    self,
                    "시리즈 이미지 프롬프트",
                    "산출물이 있다고 표시되지만 읽기 실패 — 파일을 확인하세요.",
                )
                return
            ImagePromptsDialog(prompts_data=data, parent=self).exec()
            return

        # 신규 생성 — 진행 다이얼로그 + 워커
        progress = QProgressDialog(
            "Claude — 시리즈 이미지 프롬프트 생성 중…",
            "취소",
            0,
            0,
            self,
        )
        progress.setWindowTitle("시리즈 이미지 프롬프트")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        worker = SeriesImagePromptsWorker(
            series_id=series_id,
            service=self._service,
            settings=self._settings,
            force=force,
            parent=self,
        )

        def on_ok(_sid: int, data: dict) -> None:
            progress.close()
            ImagePromptsDialog(prompts_data=data, parent=self).exec()

        def on_already(sid: int) -> None:
            # 레이스 — has_check 와 worker 사이에 다른 곳이 만든 경우. 그냥 표시.
            progress.close()
            store = ArtifactStore(self._settings.artifacts_dir)
            data = self._service.read_series_image_prompts(sid, artifact_store=store)
            if data is not None:
                ImagePromptsDialog(prompts_data=data, parent=self).exec()

        def on_fail(_sid: int, msg: str) -> None:
            progress.close()
            QMessageBox.critical(self, "시리즈 프롬프트 생성 실패", msg)

        worker.line_received.connect(
            lambda line: self._terminal.append_line(line, kind="stdout")
        )
        worker.finished_ok.connect(on_ok)
        worker.already_exists.connect(on_already)
        worker.failed.connect(on_fail)
        progress.canceled.connect(worker.requestInterruption)
        worker.start()

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

    def closeEvent(self, event: object) -> None:
        for service_attr in ("_orchestrator", "_watchdog"):
            svc = getattr(self, service_attr, None)
            if svc is not None:
                try:
                    svc.stop()
                except Exception:
                    pass
        super().closeEvent(event)  # type: ignore[arg-type]
