"""업로드 다이얼로그 — 이미지·텍스트 파일 드래그앤드롭 / 파일 선택.

흐름:
    · IMAGE / HUMANIZE 단계에서 호출.
    · 드롭 영역 + 파일 선택 버튼.
    · 검증 — MIME (whitelist), 크기 (≤ 10 MB), 경로 traversal 차단.
    · ``ArtifactStore.save_bytes`` 로 디스크 저장 + DB 기록.
    · 저장 후 단계 상태 ``AWAITING_INPUT → DONE`` 전이 시그널 emit.

P4 — 본격 구현.
"""

from __future__ import annotations


class UploadDialog:
    """드래그앤드롭 업로드 다이얼로그. P4."""
