"""EmailToBlogChannel — 네이버 블로그 메일 발행 우회 (P6 폴백).

네이버 블로그 글쓰기 API 신규 사용 신청이 거절될 경우의 대안.
사용자가 네이버 블로그 설정 → "메일로 발행" 메뉴에서 받는 발행 메일 주소를
SettingsDialog 의 별도 탭(P6 UI 추가)에서 입력하면 SMTP 로 메일을 보냄.

요구 시크릿 (keyring):
    · ``smtp_user``      — 로그인 계정
    · ``smtp_password``  — 비밀번호 (앱 비밀번호 권장)

요구 설정 (Settings):
    · ``smtp_host`` / ``smtp_port`` / ``smtp_use_tls`` — SMTP 서버
    · ``smtp_from``                                    — From 주소
    · ``naver_publish_email``                          — 발행 받는 메일

이미지 첨부는 P6 범위 외 — 본문 HTML 만 전송.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path  # noqa: TCH003 — 시그니처 호환용
from uuid import uuid4

from blogitem.channels.base import PublishChannel, PublishError, PublishResult


class EmailToBlogChannel(PublishChannel):
    """SMTP 메일 → 네이버 블로그 자동 발행."""

    name = "email_to_blog"

    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        smtp_from: str,
        publish_email: str,
        use_tls: bool = True,
        dry_run: bool = False,
    ) -> None:
        if not all([smtp_host, smtp_user, smtp_password, smtp_from, publish_email]):
            raise ValueError("SMTP / publish_email 모든 값 필요")
        if not 1 <= smtp_port <= 65535:
            raise ValueError("smtp_port out of range")

        self._host = smtp_host
        self._port = smtp_port
        self._user = smtp_user
        self._password = smtp_password
        self._from = smtp_from
        self._to = publish_email
        self._use_tls = use_tls
        self._dry_run = dry_run

    def publish(
        self,
        *,
        title: str,
        contents_html: str,
        image_paths: list[Path],
        tags: list[str] | None = None,
    ) -> PublishResult:
        if not title:
            raise ValueError("title required")
        if not contents_html:
            raise ValueError("contents_html required")

        message_id = f"<{uuid4().hex}@blogitem>"

        if self._dry_run:
            return PublishResult(channel=self.name, external_id=message_id)

        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = self._from
        msg["To"] = self._to
        msg["Message-ID"] = message_id
        msg.set_content(
            "이 메시지는 HTML 본문이 필요합니다 — HTML 표시 가능한 클라이언트에서 보세요."
        )
        msg.add_alternative(contents_html, subtype="html")

        # P6 — 이미지 첨부는 후속. 현재는 본문 안의 <img src=...> 외부 URL 만 동작.

        try:
            self._send(msg)
        except smtplib.SMTPException as e:
            # SMTPException 은 OSError 상속이라 isinstance(e, OSError) 가 True 임 — 주의.
            # SMTP 의미별 분기를 먼저: 인증/수신/송신/데이터/HELO 실패는 영구 (재시도 무의미),
            # 연결 끊김만 재시도 가능. 나머지 SMTPException 은 보수적으로 영구.
            permanent_smtp = (
                smtplib.SMTPAuthenticationError,
                smtplib.SMTPRecipientsRefused,
                smtplib.SMTPSenderRefused,
                smtplib.SMTPDataError,
                smtplib.SMTPHeloError,
                smtplib.SMTPNotSupportedError,
            )
            if isinstance(e, smtplib.SMTPServerDisconnected):
                retryable = True
            elif isinstance(e, permanent_smtp):
                retryable = False
            else:
                retryable = False
            raise PublishError(
                f"SMTP {type(e).__name__}: {e}",
                channel=self.name,
                retryable=retryable,
            ) from e
        except OSError as e:
            # 순수 네트워크/소켓 오류 (DNS, 연결 불가 등) — 재시도 가능
            raise PublishError(
                f"SMTP {type(e).__name__}: {e}",
                channel=self.name,
                retryable=True,
            ) from e

        return PublishResult(channel=self.name, external_id=message_id)

    # ── private ─────────────────────────────────────────────────────────────

    def _send(self, msg: EmailMessage) -> None:
        context = ssl.create_default_context()
        if self._port == 465:
            with smtplib.SMTP_SSL(self._host, self._port, context=context, timeout=30) as srv:
                srv.login(self._user, self._password)
                srv.send_message(msg)
        else:
            with smtplib.SMTP(self._host, self._port, timeout=30) as srv:
                srv.ehlo()
                if self._use_tls:
                    srv.starttls(context=context)
                    srv.ehlo()
                srv.login(self._user, self._password)
                srv.send_message(msg)
