"""우측 파이프라인 상세 — 6 단계 카드 스택 + 메타 정보 (P2 단순 표시).

P3+ 에서 단계별 액션 버튼(Claude 호출 / 업로드 / 컨펌) 활성화.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from blogitem.pipeline.stages import Stage

if TYPE_CHECKING:
    from blogitem.pipeline.service import PipelineService


_STAGE_LABEL: dict[Stage, str] = {
    Stage.TOPIC: "1. 주제 / 커리큘럼 (Claude · 자동)",
    Stage.IMAGE: "2. 이미지 (ChatGPT 웹 → 업로드 · 반자동)",
    Stage.DRAFT: "3. 초고 (Claude · 자동)",
    Stage.HUMANIZE: "4. 인간화 (ChatGPT 웹 → 업로드 · 반자동)",
    Stage.CONFIRM: "5. 컨펌 (사람 · 수동 게이트)",
    Stage.PUBLISH: "6. 게시 (Claude + 네이버 · 자동)",
}


class PipelineDetailWidget(QWidget):
    """선택된 파이프라인의 단계 카드 스택."""

    def __init__(
        self,
        *,
        service: PipelineService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._current_id: int | None = None

        self._title = QLabel("파이프라인을 선택하세요.", self)
        self._title.setStyleSheet(
            "font-size: 16px; font-weight: 600; padding: 12px;"
        )

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
        layout.addWidget(scroll)

    # ── 외부 API ────────────────────────────────────────────────────────────

    def show_pipeline(self, pipeline_id: int) -> None:
        """선택된 파이프라인 표시."""
        self._current_id = pipeline_id
        dto = self._service.get_pipeline(pipeline_id)
        if dto is None:
            self._title.setText(f"#{pipeline_id} (찾을 수 없음)")
            self._clear_stages()
            return

        series_part = f" · {dto.series_topic} #{dto.position}" if dto.series_topic else ""
        self._title.setText(
            f"#{dto.id} {dto.slug}{series_part}\n"
            f"  현재 단계: {dto.current_stage.value} · {dto.status.value}"
        )

        self._clear_stages()
        for stage in Stage:
            self._stages_layout.addWidget(self._make_stage_card(stage, dto.current_stage))
        self._stages_layout.addStretch(1)

    def clear(self) -> None:
        self._current_id = None
        self._title.setText("파이프라인을 선택하세요.")
        self._clear_stages()

    # ── 내부 ────────────────────────────────────────────────────────────────

    def _clear_stages(self) -> None:
        while self._stages_layout.count() > 0:
            item = self._stages_layout.takeAt(0)
            if item is None:
                break
            w = item.widget()
            if w is not None:
                w.deleteLater()

    @staticmethod
    def _make_stage_card(stage: Stage, current: Stage) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        is_current = stage == current
        card.setStyleSheet(
            "QFrame { padding: 10px 12px; border: 1px solid "
            f"{'#c4623c' if is_current else '#d9d0bc'}; border-radius: 4px; "
            f"background: {'#fcf0e9' if is_current else '#ffffff'}; }}"
        )
        layout = QVBoxLayout(card)
        title = QLabel(_STAGE_LABEL[stage])
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(title)

        hint = QLabel(
            "▶ 진행 중" if is_current else "(추후 P3+ 에서 활성화)"
        )
        hint.setStyleSheet(
            f"color: {'#c4623c' if is_current else '#7a756c'}; font-size: 11px;"
        )
        layout.addWidget(hint)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        return card
