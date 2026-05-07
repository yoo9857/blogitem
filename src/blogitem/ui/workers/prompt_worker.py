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
        from blogitem.log import get_logger

        log = get_logger(__name__)
        mode = (self._settings.llm_mode or "api").strip().lower()
        log.info("prompt_worker.start", mode=mode, prompt_len=len(self._prompt))

        if mode not in ("claude_cli", "codex_cli"):
            msg = (
                f"터미널 패널은 CLI 모드 전용입니다 (현재: {mode}). "
                "BLOGITEM_LLM_MODE 를 claude_cli 또는 codex_cli 로 변경하세요."
            )
            log.warning("prompt_worker.wrong_mode", mode=mode)
            self.failed.emit(msg)
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
            log.info("prompt_worker.client_ready", bin=client._bin_path)
        except FileNotFoundError as e:
            log.error("prompt_worker.cli_missing", err=str(e))
            self.failed.emit(str(e))
            return

        line_count = 0

        def on_line(line: str) -> None:
            nonlocal line_count
            line_count += 1
            self.line_received.emit(line)

        try:
            response = client.complete(
                system="",
                user=self._prompt,
                on_line=on_line,
            )
            log.info(
                "prompt_worker.done",
                lines=line_count,
                resp_len=len(response.text),
            )
            self.finished_ok.emit(response.text)
        except CliLlmError as e:
            log.error("prompt_worker.cli_error", err=str(e), retryable=e.retryable)
            self.failed.emit(f"CLI 실패: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("prompt_worker.unexpected", err=str(e))
            self.failed.emit(f"{type(e).__name__}: {e}")
