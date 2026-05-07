"""SeriesImagePromptsWorker — 시리즈 단위 이미지 프롬프트 생성 (Claude) 백그라운드.

ImagePromptsWorker (강의별) 와 달리 한 시리즈 전체에 대해 1회만 호출.
결과: 시리즈 썸네일 1 + 강당 본문 1 = N+1 프롬프트.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from blogitem.config import Settings
    from blogitem.pipeline.service import PipelineService


class SeriesImagePromptsWorker(QThread):
    """시리즈 단위 이미지 프롬프트 1회 생성."""

    line_received = Signal(str)
    finished_ok = Signal(int, dict)  # series_id, prompts dict
    failed = Signal(int, str)
    already_exists = Signal(int)  # series_id

    def __init__(
        self,
        *,
        series_id: int,
        service: PipelineService,
        settings: Settings,
        force: bool = False,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._series_id = series_id
        self._service = service
        self._settings = settings
        self._force = force

    def run(self) -> None:
        from blogitem.ai.prompts import PromptLibrary
        from blogitem.log import get_logger
        from blogitem.pipeline.artifacts import ArtifactStore
        from blogitem.pipeline.service import SeriesPromptsAlreadyExistsError

        log = get_logger(__name__)
        log.info(
            "series_image_prompts_worker.start",
            series_id=self._series_id,
            force=self._force,
        )

        try:
            llm = self._build_llm_client()
        except Exception as e:
            log.error("series_image_prompts_worker.llm_fail", err=str(e))
            self.failed.emit(self._series_id, f"LLM 준비 실패: {e}")
            return

        try:
            store = ArtifactStore(self._settings.artifacts_dir)
            prompts = PromptLibrary()

            data = self._service.generate_series_image_prompts(
                self._series_id,
                llm=llm,
                prompt_lib=prompts,
                artifact_store=store,
                model=self._effective_model(),
                on_line=lambda line: self.line_received.emit(line),
                force=self._force,
            )
            log.info(
                "series_image_prompts_worker.done",
                series_id=self._series_id,
                images=len(data.get("images") or []) if isinstance(data, dict) else 0,
            )
            self.finished_ok.emit(self._series_id, data)

        except SeriesPromptsAlreadyExistsError:
            log.info(
                "series_image_prompts_worker.already_exists",
                series_id=self._series_id,
            )
            self.already_exists.emit(self._series_id)
        except Exception as e:
            log.exception("series_image_prompts_worker.fail", err=str(e))
            self.failed.emit(self._series_id, f"{type(e).__name__}: {e}")

    # ── 내부 ────────────────────────────────────────────────────────────────

    def _build_llm_client(self) -> object:
        """``settings.llm_mode`` 에 따라 적절한 LlmClient — ImagePromptsWorker 와 동일."""
        mode = (self._settings.llm_mode or "api").strip().lower()

        if mode == "api":
            from blogitem import secrets
            from blogitem.ai.claude import ClaudeClient

            try:
                api_key = secrets.get("anthropic_api_key")
            except secrets.SecretMissingError as e:
                raise RuntimeError(
                    "Anthropic API 키가 설정되지 않았습니다."
                ) from e
            return ClaudeClient(
                api_key=api_key,
                default_model=self._settings.claude_model_primary,
            )

        if mode == "claude_cli":
            from blogitem.ai.cli_client import claude_cli_client

            return claude_cli_client(
                default_model=(self._settings.llm_cli_model or None),
                timeout_sec=self._settings.llm_cli_timeout_sec,
            )

        if mode == "codex_cli":
            from blogitem.ai.cli_client import codex_cli_client

            return codex_cli_client(
                default_model=(self._settings.llm_cli_model or None),
                timeout_sec=self._settings.llm_cli_timeout_sec,
            )

        raise RuntimeError(f"알 수 없는 llm_mode: {self._settings.llm_mode!r}")

    def _effective_model(self) -> str | None:
        mode = (self._settings.llm_mode or "api").strip().lower()
        if mode in ("claude_cli", "codex_cli"):
            return self._settings.llm_cli_model or None
        return self._settings.claude_model_primary
