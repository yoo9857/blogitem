"""좌측 파이프라인 목록 — QListWidget 기반 (P2 단순 구현).

P3 이후 시리즈별 그룹화·검색·필터·실시간 갱신 추가 예정.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

if TYPE_CHECKING:
    from blogitem.pipeline.service import PipelineService


_STATUS_BADGE: dict[str, str] = {
    "pending": "⏳",
    "running": "▶",
    "awaiting_input": "📥",
    "awaiting_review": "🔍",
    "done": "✓",
    "rejected": "✗",
    "failed": "⚠",
    "cancelled": "—",
}


class PipelineListWidget(QListWidget):
    """파이프라인 1행 리스트.

    Signals:
        pipeline_selected(int): 선택된 파이프라인 ID.
    """

    pipeline_selected = Signal(int)

    def __init__(
        self,
        *,
        service: PipelineService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self.setAlternatingRowColors(True)
        self.setStyleSheet(
            "QListWidget::item { padding: 8px; }"
            "QListWidget::item:selected { background: #ebe4d2; color: #0a0908; }"
        )
        self.itemSelectionChanged.connect(self._emit_selection)
        self.refresh()

    def refresh(self) -> None:
        """DB 에서 다시 로드."""
        previously_selected = self.current_pipeline_id()
        self.clear()
        for p in self._service.list_pipelines():
            badge = _STATUS_BADGE.get(p.status.value, "·")
            series_part = (
                f"  [{p.series_topic} #{p.position}]"
                if p.series_topic
                else ""
            )
            item = QListWidgetItem(
                f"#{p.id} {p.slug}{series_part}\n"
                f"  {badge} {p.current_stage.value} · {p.status.value}"
            )
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            self.addItem(item)
            if p.id == previously_selected:
                self.setCurrentItem(item)

    def current_pipeline_id(self) -> int | None:
        """현재 선택된 파이프라인 ID 또는 None."""
        items = self.selectedItems()
        if not items:
            return None
        return int(items[0].data(Qt.ItemDataRole.UserRole))

    def _emit_selection(self) -> None:
        pid = self.current_pipeline_id()
        if pid is not None:
            self.pipeline_selected.emit(pid)
