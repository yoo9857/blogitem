"""우측 파이프라인 상세 — 단계 카드 + 단계별 액션 버튼.

P3 — TOPIC 단계만 액션 활성 ("주제 생성" Claude 호출).
P3.5 — DRAFT/PUBLISH 액션 추가.
P4 — IMAGE/HUMANIZE/CONFIRM 액션 추가 (업로드/diff/컨펌).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
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
    from blogitem.ui.workers.claude_worker import ClaudeWorker


_STAGE_LABEL: dict[Stage, str] = {
    Stage.TOPIC: "1. 주제 / 커리큘럼 (Claude · 자동)",
    Stage.IMAGE: "2. 이미지 (ChatGPT 웹 → 업로드 · 반자동)",
    Stage.DRAFT: "3. 초고 (Claude · 자동)",
    Stage.HUMANIZE: "4. 인간화 (ChatGPT 웹 → 업로드 · 반자동)",
    Stage.CONFIRM: "5. 컨펌 (사람 · 수동 게이트)",
    Stage.PUBLISH: "6. 게시 (Claude + 네이버 · 자동)",
}


class PipelineDetailWidget(QWidget):
    """선택 파이프라인의 단계 카드 + 액션."""

    pipeline_changed = Signal(int)  # 단계 변경 후 부모(MainWindow) 가 목록 refresh

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
        self._claude_worker: ClaudeWorker | None = None
        self._progress: QProgressDialog | None = None

        self._title = QLabel("파이프라인을 선택하세요.", self)
        self._title.setStyleSheet(
            "font-size: 16px; font-weight: 600; padding: 12px;"
        )

        # 액션 영역 — 단계별 버튼
        self._action_area = QWidget(self)
        self._action_layout = QHBoxLayout(self._action_area)
        self._action_layout.setContentsMargins(12, 0, 12, 8)

        # 단계 카드 스택
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

        # 1단계 — TOPIC PENDING → Claude 호출 버튼
        if dto.current_stage == Stage.TOPIC and dto.status == Status.PENDING:
            btn = QPushButton("주제 생성 (Claude 호출)")
            btn.clicked.connect(lambda: self._run_topic(dto.id))
            self._action_layout.addWidget(btn)

        elif dto.current_stage == Stage.TOPIC and dto.status == Status.RUNNING:
            lbl = QLabel("⌛ Claude 처리 중…")
            lbl.setStyleSheet("color: #c4623c;")
            self._action_layout.addWidget(lbl)

        elif dto.status == Status.FAILED:
            lbl = QLabel(f"⚠ 실패 — 재시도는 P3.5 에서 활성화 ({dto.current_stage.value})")
            lbl.setStyleSheet("color: #c4623c;")
            self._action_layout.addWidget(lbl)

        else:
            # 다른 단계의 액션은 P3.5/P4 에서.
            hint = QLabel(f"({dto.current_stage.value} 단계 액션은 후속 P 에서 활성)")
            hint.setStyleSheet("color: #7a756c; font-size: 11px;")
            self._action_layout.addWidget(hint)

        self._action_layout.addStretch(1)

    # ── Claude TOPIC 호출 ───────────────────────────────────────────────────

    def _run_topic(self, pipeline_id: int) -> None:
        from blogitem.ui.workers.claude_worker import ClaudeWorker

        self._progress = QProgressDialog(
            "Claude 호출 준비…",
            "취소",
            0,
            0,
            self,
        )
        self._progress.setWindowTitle("주제 생성")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)

        self._claude_worker = ClaudeWorker(
            pipeline_id=pipeline_id,
            service=self._service,
            artifacts_dir=self._settings.artifacts_dir,
            model_primary=self._settings.claude_model_primary,
        )
        self._claude_worker.progress.connect(self._progress.setLabelText)
        self._claude_worker.finished_ok.connect(self._on_topic_ok)
        self._claude_worker.failed.connect(self._on_topic_fail)
        self._progress.canceled.connect(self._claude_worker.requestInterruption)
        self._claude_worker.finished.connect(self._progress.close)

        self._claude_worker.start()
        self._progress.exec()

    def _on_topic_ok(self, pipeline_id: int, artifact_path: str) -> None:
        QMessageBox.information(
            self,
            "주제 생성 완료",
            f"커리큘럼이 저장되었습니다.\n경로: {artifact_path}",
        )
        self.show_pipeline(pipeline_id)
        self.pipeline_changed.emit(pipeline_id)

    def _on_topic_fail(self, pipeline_id: int, message: str) -> None:
        QMessageBox.critical(self, "주제 생성 실패", message)
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

        hint = QLabel(
            "▶ 진행 중" if is_current else "(대기)"
        )
        hint.setStyleSheet(
            f"color: {'#c4623c' if is_current else '#7a756c'}; font-size: 11px;"
        )
        layout.addWidget(hint)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        return card

    # ── helper ──────────────────────────────────────────────────────────────

    @staticmethod
    def _clear_layout(layout: object) -> None:
        from PySide6.QtWidgets import QLayout

        if not isinstance(layout, QLayout):
            return
        while layout.count() > 0:
            item = layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.deleteLater()
