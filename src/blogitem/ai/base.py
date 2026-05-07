"""LLM 클라이언트 Protocol — provider 교체 가능 (Claude → 다른 모델)."""

from __future__ import annotations

from typing import Protocol


class LlmResponse:
    """LLM 응답 포장.

    Attributes:
        text: 본문 텍스트.
        model: 사용된 모델 ID.
        input_tokens: 입력 토큰 (요금/한도 추적).
        output_tokens: 출력 토큰.
        cache_read_tokens: 캐시 적중 토큰 (Anthropic prompt caching).
        cache_write_tokens: 캐시 생성 토큰.
    """

    def __init__(
        self,
        text: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        self.text = text
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_tokens = cache_read_tokens
        self.cache_write_tokens = cache_write_tokens


class LlmClient(Protocol):
    """LLM 호출 추상화. ``ClaudeClient`` 가 구현."""

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 1.0,
    ) -> LlmResponse:
        """단일 메시지 호출. 재시도 정책은 구현체 책임."""
        ...
