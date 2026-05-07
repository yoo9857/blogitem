"""런타임 설정 — env + .env 로드, pydantic 검증.

시크릿(API 키, OAuth client_secret, SMTP 비밀번호)은 여기에 두지 않는다.
``blogitem.secrets`` 의 keyring 래퍼를 사용하며, ``.env`` 는 비-시크릿 운영
옵션(DB 경로, 로그 레벨, OAuth 콜백 호스트/포트, 모델 ID, SMTP 서버)만.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """blogitem 운영 설정.

    환경변수는 ``BLOGITEM_`` prefix. 예: ``BLOGITEM_LOG_LEVEL=debug``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="BLOGITEM_",
        case_sensitive=False,
        extra="ignore",
    )

    # 로그
    log_level: str = "info"
    log_dir: Path = Path("./logs")

    # DB
    db_path: Path = Path("./data/blogitem.db")

    # 산출물
    artifacts_dir: Path = Path("./data/artifacts")

    # OAuth — 네이버 개발자센터 등록값과 일치 필수
    oauth_callback_host: str = "127.0.0.1"
    oauth_callback_port: int = Field(default=8765, ge=1024, le=65535)

    # 운영 모드
    dry_run: bool = True

    # Claude 모델 (anthropic SDK)
    claude_model_primary: str = "claude-opus-4-7"
    claude_model_fast: str = "claude-haiku-4-5-20251001"

    # ── LLM 모드 ───────────────────────────────────────────────────────────
    # api         — anthropic SDK (API 키 필요, 종량제)
    # claude_cli  — `claude` CLI subprocess (Claude Max 구독 한도 안 $0)
    # codex_cli   — `codex` CLI subprocess (ChatGPT Plus 구독 한도 안 $0)
    llm_mode: str = "api"
    llm_cli_model: str = ""           # 빈 값이면 CLI 기본 모델 사용
    llm_cli_timeout_sec: int = Field(default=600, ge=30, le=3600)

    # ── Orchestrator (자동 advance loop) ──────────────────────────────────
    # 켜면 PENDING 상태 자동 단계(TOPIC/DRAFT/PUBLISH)를 주기적으로 자동 실행.
    # CLI 모드(claude_cli/codex_cli)와 함께 쓰면 사용자 개입 없이 비용 0 으로
    # 파이프라인 자동 처리. dry_run=true 와 함께 안전하게 시작 추천.
    orchestrator_enabled: bool = False
    orchestrator_interval_min: int = Field(default=5, ge=1, le=120)

    # ── ChatGPT 웹 이미지 연동 (P10) ───────────────────────────────────────
    # 사용자가 ChatGPT 웹에서 만든 이미지를 다운로드하면 blogitem 이 자동 감지.
    # image_watch_dir — 감시할 폴더 (빈 값이면 ~/Downloads 자동 사용).
    # image_watch_window_min — 최근 N분 내 수정된 이미지만 후보로 표시.
    image_watch_dir: str = ""
    image_watch_window_min: int = Field(default=120, ge=5, le=1440)

    # ── P6: 메일 발행 폴백 ────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_use_tls: bool = True
    smtp_from: str = ""
    naver_publish_email: str = ""


def load_settings() -> Settings:
    """전역 ``Settings`` 로드. 검증 실패 시 ``ValidationError`` 즉시 raise."""
    return Settings()
