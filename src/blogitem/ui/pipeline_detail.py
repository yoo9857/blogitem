"""우측 파이프라인 상세 — 단계 카드 + 단계별 액션 (전 단계 통합).

자동 단계 (TOPIC/DRAFT/PUBLISH) — Claude 호출 버튼.
반자동 단계 (IMAGE/HUMANIZE) — 업로드 다이얼로그.
수동 단계 (CONFIRM) — 컨펌 다이얼로그 (DiffView).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from blogitem.pipeline.stages import Stage, Status

if TYPE_CHECKING:
    from blogitem.config import Settings
    from blogitem.pipeline.dto import PipelineDTO
    from blogitem.pipeline.service import PipelineService
    from blogitem.ui.workers.claude_worker import AutoStageWorker


_STAGE_LABEL: dict[Stage, str] = {
    Stage.TOPIC: "1. 주제 / 커리큘럼 (Claude · 자동)",
    Stage.IMAGE: "2. 이미지 (ChatGPT 웹 → 업로드 · 반자동)",
    Stage.DRAFT: "3. 초고 (Claude · 자동)",
    Stage.HUMANIZE: "4. 인간화 (ChatGPT 웹 → 업로드 · 반자동)",
    Stage.CONFIRM: "5. 컨펌 (사람 · 수동 게이트)",
    Stage.PUBLISH: "6. 게시 (Claude + 네이버 · 자동)",
}

_AUTO_STAGE_BUTTON_LABEL: dict[Stage, str] = {
    Stage.TOPIC: "주제 생성 (Claude)",
    Stage.DRAFT: "초고 작성 (Claude)",
    Stage.PUBLISH: "HTML 변환 + 게시 (Claude + 네이버)",
}


class PipelineDetailWidget(QWidget):
    """선택 파이프라인의 단계 카드 + 액션 영역."""

    pipeline_changed = Signal(int)
    output_line = Signal(str)  # AutoStageWorker stdout 라인 → TerminalPanel 로 전달

    def __init__(
        self,
        *,
        service: PipelineService,
        settings: Settings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._settings = settings
        self._current_id: int | None = None
        self._claude_worker: AutoStageWorker | None = None
        self._progress: QProgressDialog | None = None

        self._title = QLabel("파이프라인을 선택하세요.", self)
        self._title.setStyleSheet(
            "font-size: 16px; font-weight: 600; padding: 12px;"
        )

        self._action_area = QWidget(self)
        self._action_layout = QHBoxLayout(self._action_area)
        self._action_layout.setContentsMargins(12, 0, 12, 8)

        self._stages_container = QWidget(self)
        self._stages_layout = QVBoxLayout(self._stages_container)
        self._stages_layout.setContentsMargins(12, 0, 12, 12)
        self._stages_layout.setSpacing(8)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._stages_container)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._title)
        layout.addWidget(self._action_area)
        layout.addWidget(scroll)

    # ── 외부 API ────────────────────────────────────────────────────────────

    def show_pipeline(self, pipeline_id: int) -> None:
        self._current_id = pipeline_id
        dto = self._service.get_pipeline(pipeline_id)
        if dto is None:
            self._title.setText(f"#{pipeline_id} (찾을 수 없음)")
            self._clear_layout(self._stages_layout)
            self._clear_layout(self._action_layout)
            return

        series_part = (
            f" · {dto.series_topic} #{dto.position}" if dto.series_topic else ""
        )
        self._title.setText(
            f"#{dto.id} {dto.slug}{series_part}\n"
            f"  현재 단계: {dto.current_stage.value} · {dto.status.value}"
        )

        self._update_action_area(dto)
        self._render_stage_cards(dto.current_stage)

    def clear(self) -> None:
        self._current_id = None
        self._title.setText("파이프라인을 선택하세요.")
        self._clear_layout(self._stages_layout)
        self._clear_layout(self._action_layout)

    # ── 액션 영역 ───────────────────────────────────────────────────────────

    def _update_action_area(self, dto: PipelineDTO) -> None:
        self._clear_layout(self._action_layout)
        stage = dto.current_stage
        status = dto.status

        if status == Status.RUNNING:
            self._action_layout.addWidget(self._mk_label("⌛ 처리 중…", color="#c4623c"))

        elif status == Status.FAILED:
            self._action_layout.addWidget(
                self._mk_label("⚠ 실패 — 단계 재시도는 P5 (재큐잉) 에서.", color="#c4623c")
            )

        elif status == Status.DONE:
            self._action_layout.addWidget(self._mk_label("✓ 완료", color="#063"))

        elif stage in _AUTO_STAGE_BUTTON_LABEL and status == Status.PENDING:
            btn = QPushButton(_AUTO_STAGE_BUTTON_LABEL[stage])
            btn.clicked.connect(
                lambda checked=False, s=stage: self._run_auto_stage(dto.id, s)
            )
            self._action_layout.addWidget(btn)

        elif stage == Stage.IMAGE and status == Status.AWAITING_INPUT:
            prompts_btn = QPushButton("🎨 프롬프트 생성 (Claude)")
            prompts_btn.setToolTip(
                "Claude 가 강의 메타를 분석해 썸네일 + 본문 이미지 프롬프트 생성. "
                "결과를 ChatGPT 에 붙여넣어 이미지 만들기."
            )
            prompts_btn.clicked.connect(lambda: self._gen_image_prompts(dto.id))

            import_btn = QPushButton("📥 다운로드 임포트")
            import_btn.setToolTip(
                "ChatGPT 에서 다운받은 이미지를 폴더에서 직접 임포트. "
                "썸네일 + 메타 표시 + 다중 선택."
            )
            import_btn.clicked.connect(lambda: self._import_from_watch(dto.id))

            upload_btn = QPushButton("이미지 업로드…")
            upload_btn.clicked.connect(lambda: self._upload_image(dto.id))

            advance_btn = QPushButton("다음 단계로 →")
            advance_btn.clicked.connect(lambda: self._advance_image(dto.id))

            self._action_layout.addWidget(prompts_btn)
            self._action_layout.addWidget(import_btn)
            self._action_layout.addWidget(upload_btn)
            self._action_layout.addWidget(advance_btn)

        elif stage == Stage.HUMANIZE and status == Status.AWAITING_INPUT:
            btn = QPushButton("인간화 본문 업로드…")
            btn.clicked.connect(lambda: self._upload_humanized(dto.id))
            self._action_layout.addWidget(btn)

        elif stage == Stage.CONFIRM and status == Status.AWAITING_REVIEW:
            btn = QPushButton("컨펌 (DiffView)…")
            btn.clicked.connect(lambda: self._open_confirm(dto.id))
            self._action_layout.addWidget(btn)

        elif status == Status.REJECTED:
            self._action_layout.addWidget(
                self._mk_label("거절됨 — 4단계로 회귀, 인간화 재업로드 필요.", color="#c4623c")
            )

        else:
            self._action_layout.addWidget(
                self._mk_label(f"({stage.value}/{status.value})", color="#7a756c")
            )

        self._action_layout.addStretch(1)

    # ── 자동 단계 (Claude) ──────────────────────────────────────────────────

    def _run_auto_stage(self, pipeline_id: int, stage: Stage) -> None:
        from blogitem.ui.workers.claude_worker import AutoStageWorker

        self._progress = QProgressDialog(
            "Claude 호출 준비…",
            "취소",
            0,
            0,
            self,
        )
        self._progress.setWindowTitle(_AUTO_STAGE_BUTTON_LABEL[stage])
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)

        self._claude_worker = AutoStageWorker(
            pipeline_id=pipeline_id,
            stage=stage,
            service=self._service,
            settings=self._settings,
        )
        self._claude_worker.progress.connect(self._progress.setLabelText)
        self._claude_worker.output_line.connect(self.output_line.emit)
        self._claude_worker.finished_ok.connect(self._on_auto_ok)
        self._claude_worker.failed.connect(self._on_auto_fail)
        self._progress.canceled.connect(self._claude_worker.requestInterruption)
        self._claude_worker.finished.connect(self._progress.close)

        self._claude_worker.start()
        self._progress.exec()

    def _on_auto_ok(self, pipeline_id: int, artifact_path: str) -> None:
        QMessageBox.information(
            self,
            "단계 완료",
            f"산출물 저장: {artifact_path}",
        )
        self.show_pipeline(pipeline_id)
        self.pipeline_changed.emit(pipeline_id)

    def _on_auto_fail(self, pipeline_id: int, message: str) -> None:
        QMessageBox.critical(self, "단계 실패", message)
        self.show_pipeline(pipeline_id)
        self.pipeline_changed.emit(pipeline_id)

    # ── 이미지 프롬프트 생성 (Claude — 2단계 보조) ───────────────────────────

    def _gen_image_prompts(self, pipeline_id: int) -> None:
        from blogitem.ui.image_prompts_dialog import ImagePromptsDialog
        from blogitem.ui.workers.image_prompts_worker import ImagePromptsWorker

        progress = QProgressDialog(
            "Claude — 이미지 프롬프트 생성 중…",
            "취소",
            0,
            0,
            self,
        )
        progress.setWindowTitle("프롬프트 생성")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)

        worker = ImagePromptsWorker(
            pipeline_id=pipeline_id,
            service=self._service,
            settings=self._settings,
            body_image_count=3,
            parent=self,
        )
        worker.line_received.connect(self.output_line.emit)

        def on_ok(pid: int, data: dict) -> None:
            progress.close()
            dlg = ImagePromptsDialog(prompts_data=data, parent=self)
            dlg.exec()

        def on_fail(pid: int, msg: str) -> None:
            progress.close()
            QMessageBox.critical(self, "프롬프트 생성 실패", msg)

        worker.finished_ok.connect(on_ok)
        worker.failed.connect(on_fail)
        progress.canceled.connect(worker.requestInterruption)

        worker.start()
        progress.exec()

    def _import_from_watch(self, pipeline_id: int) -> None:
        from blogitem.image.watcher import list_recent_images, resolve_watch_dir
        from blogitem.pipeline.artifacts import ArtifactStore
        from blogitem.ui.image_import_dialog import ImageImportDialog

        watch_dir = resolve_watch_dir(self._settings.image_watch_dir)
        window_min = self._settings.image_watch_window_min

        paths = list_recent_images(watch_dir=watch_dir, max_age_min=window_min)

        dlg = ImageImportDialog(
            watch_dir=watch_dir,
            initial_paths=paths,
            parent=self,
        )
        # 새로고침 — 같은 watch_dir 다시 스캔
        dlg.refresh_requested.connect(
            lambda: dlg.set_paths(
                list_recent_images(watch_dir=watch_dir, max_age_min=window_min)
            )
        )

        if dlg.exec() != ImageImportDialog.DialogCode.Accepted:
            return

        selected = dlg.selected_paths
        if not selected:
            return

        store = ArtifactStore(self._settings.artifacts_dir)
        errors: list[str] = []
        ok_count = 0
        for path in selected:
            try:
                self._service.ingest_image(
                    pipeline_id, source_path=path, artifact_store=store
                )
                ok_count += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"{path.name}: {type(e).__name__}: {e}")

        msg = f"{ok_count}/{len(selected)} 이미지 임포트"
        if errors:
            msg += "\n\n실패:\n" + "\n".join(errors)
        QMessageBox.information(self, "임포트 결과", msg)

        self.show_pipeline(pipeline_id)
        self.pipeline_changed.emit(pipeline_id)

    # ── 이미지 업로드 (2단계) ──────────────────────────────────────────────

    def _upload_image(self, pipeline_id: int) -> None:
        from blogitem.pipeline.artifacts import ArtifactStore
        from blogitem.ui.upload_dialog import ImageUploadDialog

        dlg = ImageUploadDialog(parent=self)
        if dlg.exec() != ImageUploadDialog.DialogCode.Accepted:
            return
        paths = dlg.selected_paths
        if not paths:
            return

        store = ArtifactStore(self._settings.artifacts_dir)
        errors: list[str] = []
        ok_count = 0
        for path in paths:
            try:
                self._service.ingest_image(
                    pipeline_id, source_path=path, artifact_store=store
                )
                ok_count += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"{path.name}: {type(e).__name__}: {e}")

        msg = f"{ok_count}/{len(paths)} 이미지 등록"
        if errors:
            msg += "\n\n실패:\n" + "\n".join(errors)
        QMessageBox.information(self, "이미지 업로드 결과", msg)

        self.show_pipeline(pipeline_id)
        self.pipeline_changed.emit(pipeline_id)

    def _advance_image(self, pipeline_id: int) -> None:
        try:
            self._service.advance_image(pipeline_id)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "진행 불가", str(e))
            return
        self.show_pipeline(pipeline_id)
        self.pipeline_changed.emit(pipeline_id)

    # ── 인간화 텍스트 업로드 (4단계) ─────────────────────────────────────────

    def _upload_humanized(self, pipeline_id: int) -> None:
        from blogitem.pipeline.artifacts import ArtifactStore
        from blogitem.ui.upload_dialog import TextUploadDialog

        dlg = TextUploadDialog(
            title="인간화 본문 업로드 (4단계)",
            placeholder="ChatGPT 웹에서 인간화한 Markdown 본문을 붙여넣으세요.",
            parent=self,
        )
        if dlg.exec() != TextUploadDialog.DialogCode.Accepted:
            return

        try:
            self._service.ingest_humanized(
                pipeline_id,
                text=dlg.text,
                artifact_store=ArtifactStore(self._settings.artifacts_dir),
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "업로드 실패", f"{type(e).__name__}: {e}")
            return

        self.show_pipeline(pipeline_id)
        self.pipeline_changed.emit(pipeline_id)

    # ── 컨펌 (5단계) ────────────────────────────────────────────────────────

    def _open_confirm(self, pipeline_id: int) -> None:
        from blogitem.pipeline.artifacts import ArtifactStore
        from blogitem.ui.confirm_dialog import ConfirmDecision, ConfirmDialog

        store = ArtifactStore(self._settings.artifacts_dir)
        draft_text = self._service.read_latest_text_artifact(
            pipeline_id, Stage.DRAFT, artifact_store=store
        )
        humanized_text = self._service.read_latest_text_artifact(
            pipeline_id, Stage.HUMANIZE, artifact_store=store
        )

        if draft_text is None:
            QMessageBox.critical(self, "본문 누락", "3단계 초고 산출물이 없습니다.")
            return
        if humanized_text is None:
            QMessageBox.critical(self, "본문 누락", "4단계 인간화 산출물이 없습니다.")
            return

        dlg = ConfirmDialog(
            draft_text=draft_text,
            humanized_text=humanized_text,
            parent=self,
        )
        if dlg.exec() != ConfirmDialog.DialogCode.Accepted:
            return

        try:
            self._service.confirm_pipeline(
                pipeline_id,
                accept=(dlg.decision == ConfirmDecision.ACCEPT),
                approver="user",
                note=dlg.note,
            )
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "컨펌 처리 실패", f"{type(e).__name__}: {e}")
            return

        self.show_pipeline(pipeline_id)
        self.pipeline_changed.emit(pipeline_id)

    # ── 단계 카드 렌더 ──────────────────────────────────────────────────────

    def _render_stage_cards(self, current: Stage) -> None:
        self._clear_layout(self._stages_layout)
        for stage in Stage:
            self._stages_layout.addWidget(self._make_stage_card(stage, current))
        self._stages_layout.addStretch(1)

    @staticmethod
    def _make_stage_card(stage: Stage, current: Stage) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        is_current = stage == current
        card.setStyleSheet(
            "QFrame { padding: 10px 12px; "
            f"border: 1px solid {'#c4623c' if is_current else '#d9d0bc'}; "
            f"border-radius: 4px; "
            f"background: {'#fcf0e9' if is_current else '#ffffff'}; }}"
        )
        layout = QVBoxLayout(card)
        title = QLabel(_STAGE_LABEL[stage])
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(title)
        hint = QLabel("▶ 진행 중" if is_current else "(대기)")
        hint.setStyleSheet(
            f"color: {'#c4623c' if is_current else '#7a756c'}; font-size: 11px;"
        )
        layout.addWidget(hint)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        return card

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _mk_label(text: str, *, color: str = "#0a0908") -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {color};")
        return lbl

    @staticmethod
    def _clear_layout(layout: QLayout) -> None:
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.deleteLater()
