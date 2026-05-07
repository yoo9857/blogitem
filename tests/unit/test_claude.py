"""ClaudeClient — anthropic SDK 호출 mocking + 에러 분기."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# anthropic 패키지 미설치 시 전체 모듈 skip — uv sync 후에만 동작
anthropic = pytest.importorskip("anthropic")

from blogitem.ai.claude import ClaudeApiError, ClaudeClient  # noqa: E402


def _make_response(
    *,
    text: str,
    model: str = "claude-opus-4-7",
    input_tokens: int = 10,
    output_tokens: int = 20,
    cache_read: int = 0,
    cache_write: int = 0,
) -> MagicMock:
    """Claude API 응답을 흉내내는 mock."""
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text

    response = MagicMock()
    response.content = [text_block]
    response.model = model
    response.usage = MagicMock(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
    )
    return response


@pytest.fixture
def patched_anthropic(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """``anthropic.Anthropic`` 을 mock 으로 교체. 반환된 mock 의 ``messages.create`` 를 설정."""
    mock_client = MagicMock()
    mock_anthropic_cls = MagicMock(return_value=mock_client)
    monkeypatch.setattr("anthropic.Anthropic", mock_anthropic_cls)
    return mock_client


class TestConstructor:
    def test_empty_api_key_rejected(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            ClaudeClient(api_key="", default_model="claude-opus-4-7")

    def test_empty_model_rejected(self) -> None:
        with pytest.raises(ValueError, match="default_model"):
            ClaudeClient(api_key="sk-x", default_model="")


class TestComplete:
    def test_returns_text_and_usage(self, patched_anthropic: MagicMock) -> None:
        patched_anthropic.messages.create.return_value = _make_response(
            text="안녕!",
            input_tokens=15,
            output_tokens=42,
        )

        cc = ClaudeClient(api_key="sk-x", default_model="claude-opus-4-7")
        resp = cc.complete(system="sys", user="hi")

        assert resp.text == "안녕!"
        assert resp.input_tokens == 15
        assert resp.output_tokens == 42
        assert resp.model == "claude-opus-4-7"

    def test_uses_default_model_when_none(self, patched_anthropic: MagicMock) -> None:
        patched_anthropic.messages.create.return_value = _make_response(text="x")
        cc = ClaudeClient(api_key="sk-x", default_model="claude-haiku-4-5")
        cc.complete(system="s", user="u")
        kwargs = patched_anthropic.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-haiku-4-5"

    def test_explicit_model_overrides_default(self, patched_anthropic: MagicMock) -> None:
        patched_anthropic.messages.create.return_value = _make_response(text="x")
        cc = ClaudeClient(api_key="sk-x", default_model="claude-haiku-4-5")
        cc.complete(system="s", user="u", model="claude-opus-4-7")
        kwargs = patched_anthropic.messages.create.call_args.kwargs
        assert kwargs["model"] == "claude-opus-4-7"

    def test_combines_multiple_text_blocks(self, patched_anthropic: MagicMock) -> None:
        block1 = MagicMock(type="text", text="part1 ")
        block2 = MagicMock(type="text", text="part2")
        block_other = MagicMock(type="tool_use", text="ignored")

        response = MagicMock()
        response.content = [block1, block_other, block2]
        response.model = "claude-opus-4-7"
        response.usage = MagicMock(input_tokens=0, output_tokens=0)
        patched_anthropic.messages.create.return_value = response

        cc = ClaudeClient(api_key="sk-x", default_model="claude-opus-4-7")
        resp = cc.complete(system="s", user="u")
        assert resp.text == "part1 part2"

    def test_empty_user_rejected(self, patched_anthropic: MagicMock) -> None:
        cc = ClaudeClient(api_key="sk-x", default_model="m")
        with pytest.raises(ValueError, match="user"):
            cc.complete(system="s", user="")


class TestErrorMapping:
    def test_connection_error_retryable(
        self, patched_anthropic: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from anthropic import APIConnectionError

        # APIConnectionError requires `request` arg in newer SDK; test most lenient construction
        try:
            err = APIConnectionError(message="net", request=MagicMock())
        except TypeError:
            err = APIConnectionError(request=MagicMock())  # type: ignore[call-arg]
        patched_anthropic.messages.create.side_effect = err

        cc = ClaudeClient(api_key="sk-x", default_model="m")
        with pytest.raises(ClaudeApiError) as exc:
            cc.complete(system="s", user="u")
        assert exc.value.retryable is True

    def test_status_429_retryable(self, patched_anthropic: MagicMock) -> None:
        from anthropic import APIStatusError

        err = APIStatusError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        patched_anthropic.messages.create.side_effect = err

        cc = ClaudeClient(api_key="sk-x", default_model="m")
        with pytest.raises(ClaudeApiError) as exc:
            cc.complete(system="s", user="u")
        assert exc.value.status_code == 429
        assert exc.value.retryable is True

    def test_status_400_not_retryable(self, patched_anthropic: MagicMock) -> None:
        from anthropic import APIStatusError

        err = APIStatusError(
            message="bad request",
            response=MagicMock(status_code=400),
            body=None,
        )
        patched_anthropic.messages.create.side_effect = err

        cc = ClaudeClient(api_key="sk-x", default_model="m")
        with pytest.raises(ClaudeApiError) as exc:
            cc.complete(system="s", user="u")
        assert exc.value.retryable is False
