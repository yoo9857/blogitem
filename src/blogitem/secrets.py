"""keyring 래퍼 — OS 자격 증명 저장소.

저장 시크릿:
    - ``anthropic_api_key``
    - ``naver_oauth_client_id`` (비-시크릿이지만 한 곳에 묶음)
    - ``naver_oauth_client_secret``
    - ``naver_oauth_refresh_token`` — 갱신마다 회전
    - ``admin_password_hash`` (옵션)

플랫폼별 백엔드:
    - Windows: Credential Manager
    - macOS: Keychain
    - Linux: Secret Service / GNOME Keyring
"""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError

SERVICE = "blogitem"


class SecretMissingError(RuntimeError):
    """요청한 시크릿이 keyring 에 없음."""


def get(name: str) -> str:
    """시크릿 조회. 없으면 ``SecretMissingError``.

    예외 메시지에 시크릿 값은 절대 포함하지 않는다.
    """
    try:
        value = keyring.get_password(SERVICE, name)
    except KeyringError as e:
        raise RuntimeError(f"keyring read failed for '{name}'") from e
    if value is None:
        raise SecretMissingError(f"secret '{name}' not set in keyring")
    return value


def get_optional(name: str) -> str | None:
    """시크릿 조회 — 없으면 None."""
    try:
        return keyring.get_password(SERVICE, name)
    except KeyringError:
        return None


def set_secret(name: str, value: str) -> None:
    """시크릿 저장 / 갱신."""
    if not value:
        raise ValueError("empty secret value not allowed")
    keyring.set_password(SERVICE, name, value)


def delete(name: str) -> None:
    """시크릿 삭제. 없으면 무시."""
    try:
        keyring.delete_password(SERVICE, name)
    except KeyringError:
        pass
