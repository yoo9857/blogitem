"""네이버 OAuth 토큰 저장 — keyring + 만료/발급시각 메타.

저장 키 (``blogitem.secrets.SERVICE`` 네임스페이스):
    - ``naver_oauth_refresh_token``       — 장기 토큰 (회전 가능)
    - ``naver_oauth_access_token``        — 단기 토큰 (~1h)
    - ``naver_oauth_access_expires_at``   — Unix timestamp 문자열
    - ``naver_oauth_refresh_issued_at``   — refresh_token 최초 발급 시각
                                              (회전된 경우 갱신). 1년 만료 추적용.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from blogitem import secrets

KEY_REFRESH = "naver_oauth_refresh_token"
KEY_ACCESS = "naver_oauth_access_token"
KEY_EXPIRES_AT = "naver_oauth_access_expires_at"
KEY_REFRESH_ISSUED_AT = "naver_oauth_refresh_issued_at"


# Naver 정책 — refresh_token 은 약 1년 유효. 안전 마진 적용.
_REFRESH_TOKEN_TTL_DAYS = 365


class TokenStore:
    """네이버 OAuth 토큰 저장/회전 + 만료 추적."""

    # ── access_token ────────────────────────────────────────────────────────

    def get_access_token(self) -> str | None:
        return secrets.get_optional(KEY_ACCESS)

    def get_expires_at(self) -> datetime | None:
        return _read_timestamp(KEY_EXPIRES_AT)

    def needs_refresh(self, margin_sec: int = 60) -> bool:
        """access_token 이 ``margin_sec`` 안에 만료되거나 없으면 True."""
        exp = self.get_expires_at()
        if exp is None:
            return True
        return datetime.now() >= exp - timedelta(seconds=margin_sec)

    # ── refresh_token ───────────────────────────────────────────────────────

    def get_refresh_token(self) -> str | None:
        return secrets.get_optional(KEY_REFRESH)

    def get_refresh_issued_at(self) -> datetime | None:
        return _read_timestamp(KEY_REFRESH_ISSUED_AT)

    def days_until_refresh_expiry(self) -> int | None:
        """refresh_token 만료까지 남은 일수. 미발급 시 None."""
        issued = self.get_refresh_issued_at()
        if issued is None:
            return None
        expiry = issued + timedelta(days=_REFRESH_TOKEN_TTL_DAYS)
        delta = expiry - datetime.now()
        return max(0, delta.days)

    # ── 저장 ────────────────────────────────────────────────────────────────

    def save_pair(
        self,
        *,
        access_token: str,
        refresh_token: str,
        expires_in: int,
    ) -> None:
        """access + refresh + 만료시각 한 묶음 저장.

        refresh_token 이 새 값이거나 회전됐으면 ``issued_at`` 도 갱신.
        """
        if not access_token or not refresh_token:
            raise ValueError("empty token not allowed")

        existing_rt = secrets.get_optional(KEY_REFRESH)
        is_new_or_rotated = existing_rt != refresh_token

        secrets.set_secret(KEY_ACCESS, access_token)
        secrets.set_secret(KEY_REFRESH, refresh_token)
        secrets.set_secret(
            KEY_EXPIRES_AT,
            str((datetime.now() + timedelta(seconds=expires_in)).timestamp()),
        )

        if is_new_or_rotated:
            secrets.set_secret(
                KEY_REFRESH_ISSUED_AT,
                str(datetime.now().timestamp()),
            )

    def clear(self) -> None:
        """전체 삭제 — 재인증 필요 시."""
        secrets.delete(KEY_ACCESS)
        secrets.delete(KEY_REFRESH)
        secrets.delete(KEY_EXPIRES_AT)
        secrets.delete(KEY_REFRESH_ISSUED_AT)


def _read_timestamp(key: str) -> datetime | None:
    raw = secrets.get_optional(key)
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(float(raw))
    except (ValueError, OSError):
        return None
