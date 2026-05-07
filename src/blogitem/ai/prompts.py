"""단계별 프롬프트 카탈로그.

각 단계는 ``(system, user)`` 튜플 반환. 외부화(JSON/YAML) 가능하도록 단순 함수 형태.

언어/톤 기준 (사용자 메모리 반영):
    - 한국어, 사전식 언어 주석 금지
    - 기계스럽지 않은 사람 같은 강사 톤
    - 거래성/세일즈 카피 회피 (검색 노출용 톤은 별도)
"""

from __future__ import annotations

import json


class PromptLibrary:
    """단계별 프롬프트 생성기."""

    # ── 1단계: 주제·커리큘럼 ──────────────────────────────────────────────────

    def topic(self, *, topic: str, lecture_count: int = 20) -> tuple[str, str]:
        """1단계 — Claude 가 주제·커리큘럼 설계.

        Returns:
            (system, user). user 출력은 순수 JSON.
        """
        system = (
            "당신은 시니어 콘텐츠 기획자입니다. 한국어 블로그 시리즈의 강의 커리큘럼을 설계합니다.\n"
            "\n"
            "원칙:\n"
            "- 입문자가 첫 강의부터 마지막까지 따라갈 수 있는 학습 곡선\n"
            "- 각 강의는 고유한 주제와 측정 가능한 학습 결과 (learning outcome)\n"
            "- 실습 가능한 예제 또는 실무 적용 시나리오 포함\n"
            "- 강의 1편 분량은 블로그 한 편(약 2,000~3,500자) 범위에 적합\n"
            "- 톤은 강사처럼 자연스럽게. 기계스러운 나열 X. 거래성 카피 X.\n"
            "\n"
            "출력 형식: 순수 JSON. 코드 블록(```)이나 설명 텍스트 없이 JSON 만 출력."
        )

        schema_example = {
            "series_title": "시리즈 전체 제목 (60자 이내)",
            "series_intro": "시리즈 소개 (200자 이내)",
            "lectures": [
                {
                    "position": 1,
                    "title": "1강 제목 (60자 이내)",
                    "summary": "이번 강의에서 다룰 내용 요약 (150자 이내)",
                    "learning_outcomes": [
                        "이 강의를 마치면 무엇을 할 수 있는지 1",
                        "이 강의를 마치면 무엇을 할 수 있는지 2",
                    ],
                    "key_concepts": ["핵심 개념 1", "핵심 개념 2"],
                    "estimated_reading_min": 8,
                }
            ],
        }
        schema_str = json.dumps(schema_example, ensure_ascii=False, indent=2)

        user = (
            f"주제: {topic}\n"
            f"강의 수: {lecture_count}\n"
            f"\n"
            f"다음 JSON 스키마로 커리큘럼 작성:\n"
            f"\n"
            f"{schema_str}\n"
            f"\n"
            f"`lectures` 배열에 정확히 {lecture_count}개 요소. position 은 1부터 {lecture_count}까지 순차."
        )
        return system, user

    # ── 3단계: 초고 ─────────────────────────────────────────────────────────

    def draft(
        self,
        *,
        series_topic: str,
        lecture_meta: dict[str, object],
        image_descriptions: list[str] | None = None,
    ) -> tuple[str, str]:
        """3단계 — Claude 가 초고 작성.

        Args:
            series_topic: 전체 시리즈 주제.
            lecture_meta: 1단계 산출물 중 해당 강의 메타 ({position, title, summary, ...}).
            image_descriptions: 2단계에서 업로드된 이미지의 alt-text/설명 (있으면).
        """
        system = (
            "당신은 한국어 IT/실무 분야의 베테랑 강사 겸 작가입니다. "
            "블로그 한 편을 작성합니다.\n"
            "\n"
            "원칙:\n"
            "- 강사 톤 (반말 금지, 친근하지만 정중)\n"
            "- 단락 짧게, 소제목 자주, 코드/예시 풍부\n"
            "- 학습 결과를 본문 흐름과 자연스럽게 연결\n"
            "- 광고성/거래성 카피 X. 결론에 행동 유도(CTA) 1-2 문장 정도까지.\n"
            "- 출력 형식: Markdown."
        )

        meta_str = json.dumps(lecture_meta, ensure_ascii=False, indent=2)
        img_block = ""
        if image_descriptions:
            img_lines = "\n".join(f"- {d}" for d in image_descriptions)
            img_block = f"\n\n준비된 이미지 (본문 흐름과 어울리는 위치에 ![]() 마크 삽입 권장):\n{img_lines}"

        user = (
            f"시리즈: {series_topic}\n"
            f"\n"
            f"이번 강의 메타:\n{meta_str}{img_block}\n"
            f"\n"
            f"위 메타를 바탕으로 본문을 Markdown 으로 작성. 분량 2,000~3,500자."
        )
        return system, user

    # ── 6단계: 게시 (네이버 블로그 HTML) ──────────────────────────────────────

    def publish(
        self,
        *,
        humanized_markdown: str,
        image_paths: list[str],
    ) -> tuple[str, str]:
        """6단계 — 인간화된 Markdown 을 네이버 블로그용 HTML 로 변환 + 이미지 균등 배치."""
        system = (
            "당신은 한국어 블로그 출판 전문가입니다. Markdown 본문을 네이버 블로그에 적합한 "
            "HTML 로 변환하면서 이미지가 본문과 균등하게 흐르도록 배치합니다.\n"
            "\n"
            "원칙:\n"
            "- 의미 단위로 단락 분리\n"
            "- 이미지는 관련 단락 직후 또는 직전에 배치 — 본문 가독성 우선\n"
            "- 코드 블록은 <pre><code>...</code></pre> 사용\n"
            "- 출력은 순수 HTML. 외부 CSS/JS 참조 X."
        )
        img_lines = "\n".join(f"- {p}" for p in image_paths) or "(없음)"
        user = (
            f"본문 (Markdown):\n```\n{humanized_markdown}\n```\n"
            f"\n"
            f"사용 가능한 이미지 (서버에 이미 업로드됨 — <img src='{{이미지경로}}'> 태그로 사용):\n"
            f"{img_lines}\n"
            f"\n"
            f"위 본문을 네이버 블로그 HTML 로 변환."
        )
        return system, user
