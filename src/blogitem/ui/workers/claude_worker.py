"""ClaudeWorker — UI 차단 없이 자동 단계 실행 (현재 TOPIC 만, P3.5 에서 DRAFT/PUBLISH 추가).

시그널:
    · finished_ok(int, str)  — pipeline_id, artifact_rel_path
    · failed(int, str)        — pipeline_id, message
    · progress(str)           — UI 표시용 단계 안내
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from pathlib import Path

    from blogitem.pipeline.service import PipelineService


class ClaudeWorker(QThread):
    """1 파이프라인의 자동 단계 1회 실행."""

    finished_ok = Signal(int, str)
    failed = Signal(int, str)
    progress = Signal(str)

    def __init__(
        self,
        *,
        pipeline_id: int,
        service: PipelineService,
        artifacts_dir: Path,
        model_primary: str,
        lecture_count: int = 20,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._pipeline_id = pipeline_id
        self._service = service
        self._artifacts_dir = artifacts_dir
        self._model = model_primary
        self._lecture_count = lecture_count

    def run(self) -> None:  # noqa: D401 — QThread.run override
        from blogitem import secrets
        from blogitem.ai.claude import ClaudeApiError, ClaudeClient
        from blogitem.ai.prompts import PromptLibrary
        from blogitem.pipeline.artifacts import ArtifactStore

        try:
            api_key = secrets.get("anthropic_api_key")
        except secrets.SecretMissingError:
            self.failed.emit(
                self._pipeline_id,
                "Anthropic API 키가 설정되지 않았습니다. [설정] 에서 입력하세요.",
            )
            return

        try:
            self.progress.emit("Claude 호출 준비…")
            llm = ClaudeClient(api_key=api_key, default_model=self._model)
            prompts = PromptLibrary()
            store = ArtifactStore(self._artifacts_dir)

            self.progress.emit("Claude 호출 중 (주제·커리큘럼 설계)…")
            result = self._service.run_topic_stage(
                self._pipeline_id,
                llm=llm,
                prompt_lib=prompts,
                artifact_store=store,
                lecture_count=self._lecture_count,
                model=self._model,
            )

            if result.success and result.artifact_rel_path:
                self.finished_ok.emit(self._pipeline_id, result.artifact_rel_path)
            else:
                self.failed.emit(
                    self._pipeline_id,
                    result.error or "알 수 없는 실패",
                )
        except ClaudeApiError as e:
            self.failed.emit(self._pipeline_id, f"Claude API: {e}")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(self._pipeline_id, f"{type(e).__name__}: {e}")
