"""ImagePromptsWorker — 강의 이미지 프롬프트 생성 (Claude) 백그라운드 호출.

사용자가 IMAGE 단계의 "🎨 프롬프트 생성" 버튼을 누르면 트리거. 결과는 JSON
artifact 로 저장 + 시그널로 dict 전달 → UI 가 다이얼로그에 표시.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from blogitem.config import Settings
    from blogitem.pipeline.service import PipelineService


class ImagePromptsWorker(QThread):
    """이미지 프롬프트 1회 생성."""

    line_received = Signal(str)
    finished_ok = Signal(int, dict)  # pipeline_id, prompts dict
    failed = Signal(int, str)

    def __init__(
        self,
        *,
        pipeline_id: int,
        service: PipelineService,
        settings: Settings,
        body_image_count: int = 3,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._pipeline_id = pipeline_id
        self._service = service
        self._settings = settings
        self._body_image_count = body_image_count

    def run(self) -> None:  # noqa: D401 — QThread.run override
        from blogitem.ai.prompts import PromptLibrary
        from blogitem.log import get_logger
        from blogitem.pipeline.artifacts import ArtifactStore

        log = get_logger(__name__)
        log.info(
            "image_prompts_worker.start",
            pipeline_id=self._pipeline_id,
            body_count=self._body_image_count,
        )

        # LLM 클라이언트 — AutoStageWorker 와 동일 분기 (api/claude_cli/codex_cli)
        try:
            llm = self._build_llm_client()
        except Exception as e:  # noqa: BLE001
            log.error("image_prompts_worker.llm_fail", err=str(e))
            self.failed.emit(self._pipeline_id, f"LLM 준비 실패: {e}")
            return

        try:
            store = ArtifactStore(self._settings.artifacts_dir)
            prompts = PromptLibrary()

            record = self._service.generate_image_prompts(
                self._pipeline_id,
                llm=llm,
                prompt_lib=prompts,
                artifact_store=store,
                body_image_count=self._body_image_count,
                model=self._effective_model(),
                on_line=lambda line: self.line_received.emit(line),
            )

            # 저장된 JSON 다시 읽어 dict 로 — UI 에 즉시 표시 가능
            data = self._service.read_image_prompts(
                self._pipeline_id, artifact_store=store
            )
            if data is None:
                # 저장은 됐지만 JSON 파싱 실패 — 원본 표시
                data = {"raw": store.absolute_path(record.rel_path).read_text(encoding="utf-8")}

            log.info(
                "image_prompts_worker.done",
                pipeline_id=self._pipeline_id,
                images=len(data.get("images") or []) if isinstance(data, dict) else 0,
            )
            self.finished_ok.emit(self._pipeline_id, data)

        except Exception as e:  # noqa: BLE001
            log.exception("image_prompts_worker.fail", err=str(e))
            self.failed.emit(self._pipeline_id, f"{type(e).__name__}: {e}")

    # ── 내부 ────────────────────────────────────────────────────────────────

    def _build_llm_client(self) -> object:
        """``settings.llm_mode`` 에 따라 적절한 LlmClient — AutoStageWorker 와 동일."""
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
