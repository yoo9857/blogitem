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

    # ── P6: 메일 발행 폴백 ────────────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_use_tls: bool = True
    smtp_from: str = ""
    naver_publish_email: str = ""


def load_settings() -> Settings:
    """전역 ``Settings`` 로드. 검증 실패 시 ``ValidationError`` 즉시 raise."""
    return Settings()
