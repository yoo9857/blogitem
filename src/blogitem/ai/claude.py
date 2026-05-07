"""Claude (Anthropic) SDK 래퍼.

prompt caching, 지수 백오프 재시도, 4xx 영구 vs 5xx/429 재시도 분기,
오류 메시지에서 API 키 마스킹.

P3 — 본격 구현. 현재는 인터페이스만.
"""

from __future__ import annotations

from blogitem.ai.base import LlmResponse


class ClaudeClient:
    """Anthropic ``anthropic`` SDK 래퍼."""

    def __init__(self, api_key: str, *, default_model: str) -> None:
        if not api_key:
            raise ValueError("anthropic API key required")
        self._api_key = api_key
        self._default_model = default_model

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
    ) -> LlmResponse:
        raise NotImplementedError("P3 — 구현 필요")


class ClaudeApiError(RuntimeError):
    """Claude API 호출 실패. ``retryable`` 플래그로 재시도 분기."""

    def __init__(self, message: str, *, status_code: int, retryable: bool) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
