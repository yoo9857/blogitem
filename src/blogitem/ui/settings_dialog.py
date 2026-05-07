"""설정 다이얼로그 — API 키 / OAuth 연결 / 운영 옵션.

· Anthropic API 키 입력 → ``secrets.set_secret('anthropic_api_key', ...)``.
· 네이버 OAuth — ``client_id`` / ``client_secret`` 입력 + "연결" 버튼 →
  authorize URL 브라우저 오픈 + 임시 콜백 서버 대기.
· 운영 옵션 — ``dry_run`` 토글, 모델 선택.
· "토큰 폐기" — 재인증 강제.

P0 — 본격 구현.
"""

from __future__ import annotations


class SettingsDialog:
    """API 키 + OAuth + 운영 옵션 입력 다이얼로그. P0."""
