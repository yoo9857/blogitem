"""컨펌 다이얼로그 — 5단계 게이트.

좌(3.초고 — Claude) vs 우(4.인간화 — ChatGPT) DiffView 임베드.
승인 / 거절 / 취소 버튼. 거절 시 사유 입력 (Approval row 에 기록).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from blogitem.ui.diff_view import DiffView

if TYPE_CHECKING:
    pass


class ConfirmDecision:
    """컨펌 결과 — Accept / Reject / Cancel."""

    ACCEPT = "accept"
    REJECT = "reject"
    CANCEL = "cancel"


class ConfirmDialog(QDialog):
    """5단계 컨펌 게이트. ``decision`` / ``note`` 프로퍼티로 결과 노출."""

    def __init__(
        self,
        *,
        draft_text: str,
        humanized_text: str,
        title: str = "컨펌 — 초고 vs 인간화",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(1080, 680)

        self._decision = ConfirmDecision.CANCEL
        self._note: str | None = None

        diff = DiffView(left_label="3. 초고 (Claude)", right_label="4. 인간화 (ChatGPT)")
        diff.set_texts(draft_text, humanized_text)

        # 안내
        hint = QLabel(
            "두 본문을 비교한 뒤 [승인] 또는 [거절] 을 선택하세요. "
            "거절 시 4단계로 돌아가 인간화 본문을 다시 업로드합니다."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #4a4742; font-size: 12px; padding: 8px 0;")

        accept_btn = QPushButton("✓ 승인 (게시 진행)")
        accept_btn.setStyleSheet(
            "QPushButton { background: #063; color: #fff; padding: 9px 16px; "
            "border-radius: 3px; font-weight: 600; }"
        )
        accept_btn.clicked.connect(self._on_accept)

        reject_btn = QPushButton("✗ 거절 (인간화 재업로드)")
        reject_btn.setStyleSheet(
            "QPushButton { background: #c4623c; color: #fff; padding: 9px 16px; "
            "border-radius: 3px; font-weight: 600; }"
        )
        reject_btn.clicked.connect(self._on_reject)

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addWidget(reject_btn)
        button_row.addStretch(1)
        button_row.addWidget(cancel_btn)
        button_row.addWidget(accept_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(diff)
        layout.addLayout(button_row)

    # ── 외부 API ────────────────────────────────────────────────────────────

    @property
    def decision(self) -> str:
        return self._decision

    @property
    def note(self) -> str | None:
        return self._note

    # ── 내부 ────────────────────────────────────────────────────────────────

    def _on_accept(self) -> None:
        self._decision = ConfirmDecision.ACCEPT
        self._note = None
        self.accept()

    def _on_reject(self) -> None:
        text, ok = QInputDialog.getMultiLineText(
            self,
            "거절 사유",
            "거절 사유를 간단히 적어주세요 (선택):",
            "",
        )
        if not ok:
            return  # 입력 다이얼로그 자체 취소 — 컨펌 다이얼로그는 유지
        self._decision = ConfirmDecision.REJECT
        self._note = text.strip() or None
        self.accept()
