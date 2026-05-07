"""프롬프트 카탈로그 — 변수 치환 + 형식 안전성."""

from __future__ import annotations

import json

from blogitem.ai.prompts import PromptLibrary


class TestTopicPrompt:
    def test_returns_system_and_user(self) -> None:
        sys_p, usr_p = PromptLibrary().topic(topic="C언어 20강", lecture_count=20)
        assert "JSON" in sys_p
        assert "C언어 20강" in usr_p
        assert "20" in usr_p

    def test_includes_schema_example_as_valid_json(self) -> None:
        """프롬프트 안의 schema example 자체가 valid JSON 이어야 함."""
        _, usr = PromptLibrary().topic(topic="x", lecture_count=10)
        # ``\n\n{`` 와 ``}\n\n`lectures``` 사이의 JSON 블록 추출
        start = usr.find("{")
        end = usr.rfind("}")
        assert start >= 0 and end > start
        json_block = usr[start : end + 1]
        # 파싱 가능해야 함 (스키마 예시)
        parsed = json.loads(json_block)
        assert "series_title" in parsed
        assert "lectures" in parsed

    def test_lecture_count_interpolated(self) -> None:
        _, usr = PromptLibrary().topic(topic="x", lecture_count=7)
        assert "7개" in usr or "7 개" in usr or "7강" in usr or "7 강" in usr or "7" in usr


class TestDraftPrompt:
    def test_meta_serialized(self) -> None:
        meta = {"position": 3, "title": "변수와 자료형", "summary": "..."}
        sys_p, usr_p = PromptLibrary().draft(
            series_topic="C언어 20강", lecture_meta=meta
        )
        assert "C언어 20강" in usr_p
        assert "변수와 자료형" in usr_p
        assert "Markdown" in sys_p

    def test_image_descriptions_included(self) -> None:
        _, usr_p = PromptLibrary().draft(
            series_topic="t",
            lecture_meta={"title": "x"},
            image_descriptions=["스크린샷 1: 컴파일 결과", "다이어그램 2: 메모리 레이아웃"],
        )
        assert "스크린샷 1" in usr_p
        assert "다이어그램 2" in usr_p

    def test_no_image_descriptions_clean(self) -> None:
        _, usr_p = PromptLibrary().draft(
            series_topic="t", lecture_meta={"title": "x"}
        )
        # 이미지 설명 블록이 없으면 ``None`` 같은 문자열이 끼어들지 않아야 함
        assert "None" not in usr_p


class TestPublishPrompt:
    def test_html_focus(self) -> None:
        sys_p, usr_p = PromptLibrary().publish(
            humanized_markdown="# 제목\n\n본문",
            image_paths=["a.png", "b.png"],
        )
        assert "HTML" in sys_p
        assert "a.png" in usr_p

    def test_no_images_handled(self) -> None:
        _, usr_p = PromptLibrary().publish(
            humanized_markdown="# 제목", image_paths=[]
        )
        assert "(없음)" in usr_p
