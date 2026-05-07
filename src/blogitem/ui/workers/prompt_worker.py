"""PromptWorker — 사용자 ad-hoc 프롬프트를 LLM CLI 로 호출 (스트리밍).

TerminalPanel 의 입력 필드에서 트리거. 응답 라인이 들어올 때마다 시그널로 emit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from blogitem.config import Settings


class PromptWorker(QThread):
    """ad-hoc 프롬프트 1회 실행 (스트리밍)."""

    line_received = Signal(str)
    finished_ok = Signal(str)        # 최종 응답 텍스트
    failed = Signal(str)              # 에러 메시지

    def __init__(
        self,
        *,
        prompt: str,
        settings: Settings,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._prompt = prompt
        self._settings = settings

    def run(self) -> None:  # noqa: D401 — QThread.run override
        from blogitem.ai.cli_client import (
            CliLlmError,
            claude_cli_client,
            codex_cli_client,
        )

        mode = (self._settings.llm_mode or "api").strip().lower()
        if mode not in ("claude_cli", "codex_cli"):
            self.failed.emit(
                f"터미널 패널은 CLI 모드 전용입니다 (현재: {mode}). "
                "BLOGITEM_LLM_MODE 를 claude_cli 또는 codex_cli 로 변경하세요."
            )
            return

        try:
            if mode == "claude_cli":
                client = claude_cli_client(
                    default_model=(self._settings.llm_cli_model or None),
                    timeout_sec=self._settings.llm_cli_timeout_sec,
                )
            else:
                client = codex_cli_client(
                    default_model=(self._settings.llm_cli_model or None),
                    timeout_sec=self._settings.llm_cli_timeout_sec,
                )
        except FileNotFoundError as e:
            self.failed.emit(str(e))
            return

        try:
            response = client.complete(
                system="",
                user=self._prompt,
                on_line=lambda line: self.line_received.emit(line),
            )
            self.finished_ok.emit(response.text)
        except CliLlmError as e:
            self.failed.emit(f"CLI 실패: {e}")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"{type(e).__name__}: {e}")
