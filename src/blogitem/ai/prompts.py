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

    # ── 2단계 보조: 이미지 프롬프트 생성 (Claude → 사용자 → ChatGPT 웹) ─────

    def image_prompts(
        self,
        *,
        lecture_meta: dict[str, object],
        series_topic: str | None = None,
        body_image_count: int = 3,
    ) -> tuple[str, str]:
        """강의별 이미지 프롬프트 N+1 개 생성 (썸네일 1 + 본문 중요 부분 N).

        사용자는 결과 프롬프트를 ChatGPT 웹에 붙여넣어 이미지 생성 후 다운로드.
        blogitem 의 워치 폴더가 자동 감지 → 임포트.

        Args:
            lecture_meta: 1단계 산출물의 lecture 객체 (title/summary/key_concepts).
            series_topic: 시리즈 전체 주제.
            body_image_count: 본문 중간에 들어갈 이미지 수 (기본 3, 권장 2~5).

        Returns:
            (system, user). user 출력은 순수 JSON — 프롬프트 N+1 개 배열.
        """
        system = (
            "당신은 한국어 블로그용 시각자료를 설계하는 시니어 디자이너입니다. "
            "강의 1편에 들어갈 이미지 프롬프트를 작성합니다 — 사용자가 ChatGPT 웹에 "
            "붙여넣어 이미지를 생성하기 위한 영문/한국어 혼용 프롬프트.\n"
            "\n"
            "원칙:\n"
            "- 썸네일 1장: 강의 전체를 대표 — 제목 + 핵심 개념 시각화\n"
            "- 본문 이미지 N장: 본문에서 다룰 핵심 포인트별로 1장씩\n"
            "- 한 강의 안에서 이미지들이 시각적으로 일관 (같은 색감/스타일/구도)\n"
            "- 텍스트는 영어 키워드 1~2개만 (한국어 텍스트는 깨질 수 있음)\n"
            "- 1024x1024 정사각형 권장 (블로그 본문 폭에 적합)\n"
            "- 스타일: Editorial illustration / 미니멀 / 차분한 채도 (cream / ink / terracotta)\n"
            "\n"
            "출력 형식: 순수 JSON. 코드 블록(```)이나 설명 텍스트 없이 JSON 만."
        )

        schema_example = {
            "style_guide": "한 강의 내 이미지들의 공통 시각 스타일 (1-2 문장)",
            "images": [
                {
                    "role": "thumbnail",
                    "position": 0,
                    "purpose": "왜 이 이미지가 필요한가 (1 문장)",
                    "prompt": (
                        "ChatGPT 에 붙여넣을 영문/한국어 혼용 프롬프트. "
                        "구도·요소·텍스트키워드·스타일 모두 포함."
                    ),
                },
                {
                    "role": "body",
                    "position": 1,
                    "purpose": "본문 1번 위치 — 어떤 개념을 시각화하는가",
                    "prompt": "...",
                },
            ],
        }
        schema_str = json.dumps(schema_example, ensure_ascii=False, indent=2)

        meta_str = json.dumps(lecture_meta, ensure_ascii=False, indent=2)
        n_body = max(1, min(5, body_image_count))
        total = n_body + 1  # +1 thumbnail

        topic_line = f"시리즈 주제: {series_topic}\n" if series_topic else ""

        user = (
            f"{topic_line}"
            f"강의 메타:\n{meta_str}\n"
            f"\n"
            f"위 강의에 어울리는 이미지 프롬프트를 다음 JSON 스키마로 작성:\n"
            f"\n"
            f"{schema_str}\n"
            f"\n"
            f"`images` 배열에 정확히 {total}개 — 썸네일 1개 (role=thumbnail, position=0) "
            f"+ 본문 {n_body}개 (role=body, position=1..{n_body})."
        )
        return system, user

    # ── 2단계 보조: 시리즈 단위 이미지 프롬프트 ────────────────────────────────

    def series_image_prompts(
        self,
        *,
        series_topic: str,
        lectures: list[dict[str, object]],
    ) -> tuple[str, str]:
        """시리즈 전체 이미지 프롬프트 — 시리즈 썸네일 1장 + 강당 본문 1장.

        강의가 N개면 출력 프롬프트는 N+1개 (썸네일 1 + 본문 N).
        각 본문 프롬프트는 ``lecture_position``/``lecture_title`` 로 강의에 매핑.
        사용자는 결과를 ChatGPT 웹에 붙여넣어 이미지 생성 후 다운로드.

        Args:
            series_topic: 시리즈 전체 제목/주제 (썸네일 컨텍스트).
            lectures: 1단계 산출물의 ``lectures`` 배열 — 각 항목은
                ``{position, title, summary, key_concepts, ...}`` dict.

        Returns:
            (system, user). user 출력은 순수 JSON.
        """
        system = (
            "당신은 한국어 IT 강의 교재의 시각자료를 설계하는 시니어 인스트럭셔널 "
            "디자이너입니다. 강사가 강의에서 그대로 보여줄 수 있는 '교재형 "
            "다이어그램' 이미지를 위한 프롬프트를 작성합니다 — 사용자가 ChatGPT 웹에 "
            "붙여넣어 이미지를 생성하기 위한 영문 프롬프트.\n"
            "\n"
            "톤 (절대 원칙):\n"
            "- 전문 강사 / 대학 교재 / 기술 문서 톤 — 신뢰감 있고 정돈됨\n"
            "- 'cute', 'playful', 'whimsical', 'cartoonish', 'fun' 같은 형용사 절대 X\n"
            "- 'tiny floating <symbol>', 'decorative motifs', 'glowing softly' 같은 "
            "장식 요소 절대 X — 핵심 개념 시각화 외에 떠다니는 기호/장식 금지\n"
            "- 화면에 들어가는 요소 5개 이내, 각 요소는 강의 핵심 개념을 직접 설명\n"
            "\n"
            "구성 원칙:\n"
            "- 시리즈 썸네일 1장: 시리즈 전체 주제 — 메인 키워드 1~2개를 큰 타이포 + "
            "심볼 1개로 표현. 깔끔한 표지/커버 느낌.\n"
            "- 강당 본문 1장: 강의 핵심 개념의 다이어그램 — 박스/화살표/라벨로 "
            "정확하게 설명. 메모리 그림, 플로우 차트, 컴포넌트 관계도 같은 형식.\n"
            "- 시리즈 안에서 모든 이미지가 시각적으로 일관 (같은 색감/선 굵기/타이포)\n"
            "\n"
            "스타일 가이드 (영문 프롬프트에 그대로 사용):\n"
            "- 'Clean technical diagram, instructional textbook style'\n"
            "- 'Flat vector, minimal, sharp lines, professional'\n"
            "- 1024x1024 square, generous white/neutral background\n"
            "- 색감: muted, 2-3색 제한 (예: cream/ink/terracotta 또는 white/navy/red)\n"
            "- 텍스트는 영어 라벨만 (한국어 X — 깨짐). 라벨은 박스 옆/안에 배치.\n"
            "- gradient 금지, glow 금지, 그림자 최소.\n"
            "\n"
            "출력 형식: 순수 JSON. 코드 블록(```)이나 설명 텍스트 없이 JSON 만."
        )

        # 강의 메타 — 토큰 절약 위해 핵심 필드만 추출
        compact_lectures: list[dict[str, object]] = []
        for lec in lectures:
            if not isinstance(lec, dict):
                continue
            compact_lectures.append(
                {
                    "position": lec.get("position"),
                    "title": lec.get("title"),
                    "summary": lec.get("summary"),
                    "key_concepts": lec.get("key_concepts") or [],
                }
            )
        n_body = len(compact_lectures)
        total = n_body + 1  # +1 thumbnail

        schema_example = {
            "style_guide": "시리즈 전체 이미지의 공통 시각 스타일 (1-2 문장)",
            "images": [
                {
                    "role": "thumbnail",
                    "position": 0,
                    "lecture_position": None,
                    "lecture_title": None,
                    "purpose": "시리즈 전체를 대표하는 썸네일 (1 문장)",
                    "prompt": (
                        "ChatGPT 에 붙여넣을 영문/한국어 혼용 프롬프트. "
                        "시리즈 제목 + 시리즈 전체 핵심 콘셉트 + 스타일."
                    ),
                },
                {
                    "role": "body",
                    "position": 1,
                    "lecture_position": 1,
                    "lecture_title": "1강 제목 (그대로 복사)",
                    "purpose": "1강의 학습 포인트를 시각화",
                    "prompt": "...",
                },
            ],
        }
        schema_str = json.dumps(schema_example, ensure_ascii=False, indent=2)
        lectures_str = json.dumps(compact_lectures, ensure_ascii=False, indent=2)

        user = (
            f"시리즈 주제: {series_topic}\n"
            f"강의 수: {n_body}\n"
            f"\n"
            f"강의 목록:\n{lectures_str}\n"
            f"\n"
            f"위 시리즈에 들어갈 이미지 프롬프트를 다음 JSON 스키마로 작성:\n"
            f"\n"
            f"{schema_str}\n"
            f"\n"
            f"`images` 배열에 정확히 {total}개:\n"
            f"- 썸네일 1개 (role=thumbnail, position=0, lecture_position=null)\n"
            f"- 본문 {n_body}개 (role=body, position=1..{n_body}, "
            f"각 본문의 lecture_position 은 위 강의 목록의 position 과 일치, "
            f"lecture_title 은 그 강의 제목 그대로 복사)."
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
