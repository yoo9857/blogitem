"""이미지 프롬프트 빌더 — 강의 메타 → ChatGPT 웹에 붙여넣을 한국어 프롬프트."""

from __future__ import annotations

from typing import Any


def build_image_prompt(
    *,
    lecture_meta: dict[str, Any],
    series_topic: str | None = None,
    image_count: int = 1,
) -> str:
    """블로그 강의용 이미지 생성 프롬프트.

    Args:
        lecture_meta: 1단계 산출물의 lecture 객체 (title/summary/key_concepts).
        series_topic: 시리즈 전체 주제 (있으면 컨텍스트에 포함).
        image_count: 1편당 이미지 장수 (1~5 권장).

    Returns:
        ChatGPT 웹에 그대로 붙여넣어 이미지 생성을 요청하는 한국어 프롬프트.
        결과 이미지는 사용자가 다운로드해서 blogitem 으로 임포트.
    """
    title = str(lecture_meta.get("title") or "").strip()
    summary = str(lecture_meta.get("summary") or "").strip()
    key_concepts = lecture_meta.get("key_concepts") or []
    if not isinstance(key_concepts, list):
        key_concepts = []

    context_lines: list[str] = []
    if series_topic:
        context_lines.append(f"시리즈: {series_topic}")
    if title:
        context_lines.append(f"강의 제목: {title}")
    if summary:
        context_lines.append(f"내용 요약: {summary}")
    if key_concepts:
        joined = ", ".join(str(c) for c in key_concepts[:6] if c)
        if joined:
            context_lines.append(f"핵심 개념: {joined}")

    context = "\n".join(context_lines) if context_lines else "(블로그 강의)"
    n = max(1, min(5, image_count))
    plural = f"{n}장" if n > 1 else "1장"

    return (
        f"다음 블로그 강의에 어울리는 시각자료 이미지 {plural} 만들어주세요.\n"
        f"\n"
        f"{context}\n"
        f"\n"
        f"요청 스타일:\n"
        f"- 1024x1024 정사각형 권장 (블로그 본문 가로폭에 적합)\n"
        f"- 깔끔한 일러스트레이션 — Editorial / 플랫 / 미니멀\n"
        f"- 텍스트는 영어 키워드 1~2개만 (한국어 텍스트는 깨질 수 있어 X)\n"
        f"- 학습용 친근한 분위기, 채도는 차분하게 (크림/잉크/테라코타 같은 톤)\n"
        f"- 이미지마다 본문에서 다룰 다른 측면을 보여주세요 (반복 X)\n"
        f"\n"
        f"각 이미지를 1024x1024 PNG 로 만든 뒤 다운로드 가능하게 표시해주세요."
    )
