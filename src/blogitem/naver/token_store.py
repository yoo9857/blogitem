"""네이버 OAuth 토큰 저장 — keyring (1급) + 만료시각 메타.

저장 키 (``blogitem.secrets.SERVICE`` 네임스페이스):
    - ``naver_oauth_refresh_token`` — 장기 토큰 (회전됨)
    - ``naver_oauth_access_token`` — 단기 토큰 (~1h)
    - ``naver_oauth_access_expires_at`` — Unix timestamp 문자열

P1 — 본격 구현.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from blogitem import secrets

KEY_REFRESH = "naver_oauth_refresh_token"
KEY_ACCESS = "naver_oauth_access_token"
KEY_EXPIRES_AT = "naver_oauth_access_expires_at"


class TokenStore:
    """네이버 OAuth 토큰 저장/회전.

    Notes:
        access_token 만료 임박(60s 마진) 시 refresh 가 필요한지 ``needs_refresh()`` 로 판단.
        refresh 후엔 ``save_pair()`` 로 atomic 갱신.
    """

    def get_refresh_token(self) -> str | None:
        return secrets.get_optional(KEY_REFRESH)

    def get_access_token(self) -> str | None:
        return secrets.get_optional(KEY_ACCESS)

    def get_expires_at(self) -> datetime | None:
        raw = secrets.get_optional(KEY_EXPIRES_AT)
        if raw is None:
            return None
        try:
            return datetime.fromtimestamp(float(raw))
        except (ValueError, OSError):
            return None

    def needs_refresh(self, margin_sec: int = 60) -> bool:
        """access_token 이 곧 만료되거나 없으면 True."""
        exp = self.get_expires_at()
        if exp is None:
            return True
        return datetime.now() >= exp - timedelta(seconds=margin_sec)

    def save_pair(self, *, access_token: str, refresh_token: str, expires_in: int) -> None:
        """access + refresh + 만료시각 한 묶음으로 저장."""
        if not access_token or not refresh_token:
            raise ValueError("empty token not allowed")
        secrets.set_secret(KEY_ACCESS, access_token)
        secrets.set_secret(KEY_REFRESH, refresh_token)
        secrets.set_secret(
            KEY_EXPIRES_AT,
            str((datetime.now() + timedelta(seconds=expires_in)).timestamp()),
        )

    def clear(self) -> None:
        """전체 삭제 — 재인증 필요 시."""
        secrets.delete(KEY_ACCESS)
        secrets.delete(KEY_REFRESH)
        secrets.delete(KEY_EXPIRES_AT)
