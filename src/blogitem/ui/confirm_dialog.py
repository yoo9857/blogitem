"""컨펌 다이얼로그 — 5단계 게이트.

· DiffView 임베드.
· 액션: ``승인`` (DONE) / ``거절`` (REJECTED — HUMANIZE 재실행) / ``취소`` (CANCELLED).
· 거절 시 사유 입력 — ``Approval`` row 기록.

P4 — 본격 구현.
"""

from __future__ import annotations


class ConfirmDialog:
    """컨펌 게이트 다이얼로그. P4."""
