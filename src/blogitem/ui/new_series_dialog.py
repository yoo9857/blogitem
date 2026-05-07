"""새 시리즈/강의 생성 다이얼로그."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from blogitem.pipeline.dto import SeriesDTO
    from blogitem.pipeline.service import PipelineService


class NewSeriesDialog(QDialog):
    """주제 + 강의 수 입력 → 시리즈/파이프라인 일괄 생성."""

    def __init__(
        self,
        *,
        service: PipelineService,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("새 시리즈")
        self.setMinimumWidth(440)
        self._service = service
        self._created: SeriesDTO | None = None

        self._topic = QLineEdit(self)
        self._topic.setPlaceholderText("예: C언어 20강 완벽한 커리큘럼")

        self._count = QSpinBox(self)
        self._count.setRange(1, 100)
        self._count.setValue(20)
        self._count.setSuffix(" 강")

        form = QFormLayout()
        form.addRow("주제:", self._topic)
        form.addRow("강의 수:", self._count)

        info = QLabel(
            "시리즈 + 파이프라인 N 개가 생성됩니다 (각 파이프라인 = 1 블로그 글).\n"
            "1단계(TOPIC)는 PENDING 상태로 시작 — Claude 가 차례로 처리."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #7a756c; font-size: 12px;")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(info)
        layout.addWidget(buttons)

    # ── Save ────────────────────────────────────────────────────────────────

    def _save(self) -> None:
        topic = self._topic.text().strip()
        if not topic:
            QMessageBox.warning(self, "검증 실패", "주제를 입력하세요.")
            return

        try:
            self._created = self._service.create_series_with_pipelines(
                topic=topic,
                lecture_count=self._count.value(),
            )
            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "검증 실패", str(e))
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(
                self,
                "생성 실패",
                f"{type(e).__name__}: {e}",
            )

    @property
    def created(self) -> SeriesDTO | None:
        """저장 성공 시 생성된 ``SeriesDTO``, 실패/취소 시 None."""
        return self._created
