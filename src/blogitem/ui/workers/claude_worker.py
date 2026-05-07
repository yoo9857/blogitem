"""ClaudeWorker — Claude API 호출 ``QThread``.

Signals:
    · finished(LlmResponse)
    · failed(str)
    · progress(str)   # 단계 표시

P3 — 본격 구현.
"""

from __future__ import annotations


class ClaudeWorker:
    """``QThread`` 상속 — Claude 호출. P3."""
