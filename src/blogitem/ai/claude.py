"""Claude (Anthropic) SDK 래퍼 — 동기 호출, 에러 분기, 토큰 사용량 노출.

원칙:
    · API 키는 ``__init__`` 에서만 받음 — 메서드 인자/예외 메시지에 절대 노출 X.
    · 에러는 ``ClaudeApiError(retryable=...)`` 로 분기 — 4xx 영구, 429/5xx 재시도.
    · 응답에서 ``content`` 블록 중 ``type == "text"`` 만 합쳐서 반환.
    · 사용량(usage) — 캐시 hits 포함 노출 (호출 측이 비용 추적 가능).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from blogitem.ai.base import LlmResponse

if TYPE_CHECKING:
    from anthropic import Anthropic


class ClaudeApiError(RuntimeError):
    """Claude API 호출 실패."""

    def __init__(self, message: str, *, status_code: int = 0, retryable: bool = False) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class ClaudeClient:
    """Anthropic ``messages.create`` 래퍼.

    SDK 인스턴스는 lazy 생성 — 테스트에서 ``Anthropic`` 자체를 monkeypatch 가능.
    """

    def __init__(self, *, api_key: str, default_model: str) -> None:
        if not api_key:
            raise ValueError("api_key required")
        if not default_model:
            raise ValueError("default_model required")
        self._api_key = api_key
        self._default_model = default_model
        self._client: Anthropic | None = None

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 1.0,
    ) -> LlmResponse:
        """단일 메시지 호출. 시스템 + 유저 프롬프트.

        Returns:
            ``LlmResponse`` — text + 사용량.

        Raises:
            ClaudeApiError: 호출 실패 (``retryable`` 로 재시도 분기).
        """
        if not user:
            raise ValueError("user prompt required")

        from anthropic import APIConnectionError, APIError, APIStatusError

        client = self._get_client()
        try:
            response = client.messages.create(
                model=model or self._default_model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except APIConnectionError as e:
            raise ClaudeApiError(
                f"network: {type(e).__name__}",
                status_code=0,
                retryable=True,
            ) from e
        except APIStatusError as e:
            status = int(e.status_code or 0)
            retryable = status == 429 or status >= 500
            raise ClaudeApiError(
                f"HTTP {status}",
                status_code=status,
                retryable=retryable,
            ) from e
        except APIError as e:
            raise ClaudeApiError(
                f"api: {type(e).__name__}",
                status_code=0,
                retryable=False,
            ) from e

        text = self._extract_text(response)
        usage = response.usage
        return LlmResponse(
            text=text,
            model=str(response.model),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        )

    # ── private ─────────────────────────────────────────────────────────────

    def _get_client(self) -> Anthropic:
        if self._client is None:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self._api_key)
        return self._client

    @staticmethod
    def _extract_text(response: object) -> str:
        """``response.content`` 의 ``TextBlock`` 들만 합쳐 반환."""
        content = getattr(response, "content", None)
        if not content:
            return ""
        parts: list[str] = []
        for block in content:
            if getattr(block, "type", None) == "text":
                txt = getattr(block, "text", "")
                if isinstance(txt, str):
                    parts.append(txt)
        return "".join(parts)
