"""DiffView — 3.초고(Claude) vs 4.인간화(ChatGPT) side-by-side 비교.

목적: 컨펌 단계(5)에서 사람이 두 본문을 동시에 보고 결정.
P4 — 본격 구현.
"""

from __future__ import annotations


class DiffView:
    """좌·우 두 본문 비교. 단어 단위 diff 강조. P4."""
