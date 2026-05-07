"""단계별 프롬프트 카탈로그 — 시스템 프롬프트 + 변수 치환.

원칙:
    · 프롬프트는 코드와 분리 가능해야 함 (외부화 옵션 — JSON/YAML 파일).
    · 단계별 system / user 템플릿을 메서드로 노출.
    · 출력 형식(JSON 스키마 등)을 명시적으로 지정.

P3 — 본격 구현. 현재는 시그니처만.
"""

from __future__ import annotations


class PromptLibrary:
    """단계별 프롬프트 생성기."""

    def topic(self, seed: str, *, lecture_count: int = 20) -> tuple[str, str]:
        """1단계 — Claude 가 주제·커리큘럼 설계.

        Returns:
            ``(system, user)`` 튜플.
        """
        raise NotImplementedError("P3 — 프롬프트 작성 필요")

    def draft(self, *, topic: str, outline_node: str, image_descriptions: list[str]) -> tuple[str, str]:
        """3단계 — Claude 가 초고 작성. 이미지 설명을 본문 흐름과 연동."""
        raise NotImplementedError("P3 — 프롬프트 작성 필요")

    def publish(self, *, draft: str, humanized: str, image_paths: list[str]) -> tuple[str, str]:
        """6단계 — Claude 가 텍스트·이미지 균등 분할 + 네이버 게시 HTML 생성."""
        raise NotImplementedError("P3 — 프롬프트 작성 필요")
