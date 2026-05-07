"""AutoStageWorker — TOPIC/DRAFT/PUBLISH 자동 단계 백그라운드 실행.

LLM 백엔드는 ``settings.llm_mode`` 로 결정 (api / claude_cli / codex_cli).
파일명은 ``claude_worker`` 로 유지 — 외부 import 호환. ``ClaudeWorker`` 별칭 잔존.

시그널:
    · finished_ok(int, str)   — pipeline_id, artifact_rel_path
    · failed(int, str)         — pipeline_id, message
    · progress(str)            — UI 표시용 진행 메시지
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

from blogitem.pipeline.stages import Stage

if TYPE_CHECKING:
    from blogitem.ai.base import LlmClient
    from blogitem.config import Settings
    from blogitem.pipeline.service import PipelineService


class AutoStageWorker(QThread):
    """1 파이프라인의 자동 단계(TOPIC/DRAFT/PUBLISH) 1회 실행."""

    finished_ok = Signal(int, str)
    failed = Signal(int, str)
    progress = Signal(str)

    def __init__(
        self,
        *,
        pipeline_id: int,
        stage: Stage,
        service: PipelineService,
        settings: Settings,
        lecture_count: int = 20,
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)  # type: ignore[arg-type]
        self._pipeline_id = pipeline_id
        self._stage = stage
        self._service = service
        self._settings = settings
        self._lecture_count = lecture_count

    def run(self) -> None:  # noqa: D401 — QThread.run override
        if self._stage not in (Stage.TOPIC, Stage.DRAFT, Stage.PUBLISH):
            self.failed.emit(
                self._pipeline_id,
                f"자동 실행이 아닌 단계: {self._stage.value}",
            )
            return

        from blogitem.ai.prompts import PromptLibrary
        from blogitem.pipeline.artifacts import ArtifactStore

        # ── LLM 클라이언트 준비 (mode 분기) ──────────────────────────────────
        try:
            llm = self._build_llm_client()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(self._pipeline_id, f"LLM 준비 실패: {e}")
            return

        try:
            prompts = PromptLibrary()
            store = ArtifactStore(self._settings.artifacts_dir)

            if self._stage == Stage.TOPIC:
                self.progress.emit(self._stage_message("주제·커리큘럼 설계"))
                result = self._service.run_topic_stage(
                    self._pipeline_id,
                    llm=llm,
                    prompt_lib=prompts,
                    artifact_store=store,
                    lecture_count=self._lecture_count,
                    model=self._effective_model(),
                )
            elif self._stage == Stage.DRAFT:
                self.progress.emit(self._stage_message("초고 작성"))
                result = self._service.run_draft_stage(
                    self._pipeline_id,
                    llm=llm,
                    prompt_lib=prompts,
                    artifact_store=store,
                    model=self._effective_model(),
                )
            else:  # Stage.PUBLISH
                self.progress.emit(self._stage_message("HTML 변환 + 채널 게시"))
                channel = self._make_channel()
                result = self._service.run_publish_stage(
                    self._pipeline_id,
                    llm=llm,
                    prompt_lib=prompts,
                    artifact_store=store,
                    channel=channel,
                    model=self._effective_model(),
                )

            if result.success and result.artifact_rel_path:
                self.finished_ok.emit(self._pipeline_id, result.artifact_rel_path)
            else:
                self.failed.emit(self._pipeline_id, result.error or "알 수 없는 실패")

        except Exception as e:  # noqa: BLE001
            self.failed.emit(self._pipeline_id, f"{type(e).__name__}: {e}")

    # ── LLM 백엔드 빌드 ─────────────────────────────────────────────────────

    def _build_llm_client(self) -> LlmClient:
        """``settings.llm_mode`` 에 따라 적절한 LlmClient 반환."""
        mode = (self._settings.llm_mode or "api").strip().lower()

        if mode == "api":
            from blogitem import secrets
            from blogitem.ai.claude import ClaudeClient

            try:
                api_key = secrets.get("anthropic_api_key")
            except secrets.SecretMissingError as e:
                raise RuntimeError(
                    "Anthropic API 키가 설정되지 않았습니다. [설정] 에서 입력하세요."
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

        raise RuntimeError(
            f"알 수 없는 llm_mode: {self._settings.llm_mode!r} "
            "(허용: api | claude_cli | codex_cli)"
        )

    def _effective_model(self) -> str | None:
        """현재 모드에서 사용할 모델 ID. CLI 모드면 settings.llm_cli_model, 아니면 primary."""
        mode = (self._settings.llm_mode or "api").strip().lower()
        if mode in ("claude_cli", "codex_cli"):
            return self._settings.llm_cli_model or None
        return self._settings.claude_model_primary

    def _stage_message(self, label: str) -> str:
        mode = (self._settings.llm_mode or "api").strip().lower()
        prefix = {
            "api": "Claude API",
            "claude_cli": "claude CLI",
            "codex_cli": "codex CLI",
        }.get(mode, "LLM")
        return f"{prefix} — {label}"

    # ── 네이버 채널 조립 ────────────────────────────────────────────────────

    def _make_channel(self) -> object:
        from blogitem import secrets
        from blogitem.channels.naver import NaverChannel
        from blogitem.naver.oauth import OAuthClient
        from blogitem.naver.token_store import TokenStore

        client_id = secrets.get("naver_oauth_client_id")
        client_secret = secrets.get("naver_oauth_client_secret")
        redirect_uri = (
            f"http://{self._settings.oauth_callback_host}"
            f":{self._settings.oauth_callback_port}/naver-callback"
        )
        oauth = OAuthClient(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
        return NaverChannel(
            oauth_client=oauth,
            token_store=TokenStore(),
            dry_run=self._settings.dry_run,
        )


# ── 호환 별칭 ──────────────────────────────────────────────────────────────────

#: Deprecated — ``AutoStageWorker`` 를 직접 사용하세요.
ClaudeWorker = AutoStageWorker
