"""StageCard — 파이프라인 단계별 산출물 미리보기 + 이미지 썸네일 카드.

기존 단순 카드를 풍성한 미리보기로 확장:
    · 텍스트 단계 (TOPIC/DRAFT/HUMANIZE/PUBLISH HTML) — 첫 ~240자 미리보기
    · 이미지 단계 (IMAGE) — 가로 썸네일 스트립 (최대 6장 + ``+N more`` 라벨)
    · 이미지 프롬프트 단계 — "프롬프트 N개 생성됨" 표시
    · 게시 단계 — external_id 표시 (PUBLISH 의 Approval row 에서)
    · 산출물 클릭 → ArtifactViewerDialog 로 풀 컨텐츠 보기
"""

from __future__ import annotations

import json
from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from blogitem.pipeline.stages import Stage, Status

if TYPE_CHECKING:
    from blogitem.pipeline.dto import ArtifactSummary


_STAGE_LABEL: dict[Stage, str] = {
    Stage.TOPIC: "1. 주제 / 커리큘럼 (Claude · 자동)",
    Stage.IMAGE: "2. 이미지 (ChatGPT 웹 → 업로드 · 반자동)",
    Stage.DRAFT: "3. 초고 (Claude · 자동)",
    Stage.HUMANIZE: "4. 인간화 (ChatGPT 웹 → 업로드 · 반자동)",
    Stage.CONFIRM: "5. 컨펌 (사람 · 수동 게이트)",
    Stage.PUBLISH: "6. 게시 (Claude + 네이버 · 자동)",
}

_STATUS_HINT: dict[Status, str] = {
    Status.PENDING: "⏳ 대기",
    Status.RUNNING: "▶ 진행 중",
    Status.AWAITING_INPUT: "📥 입력 대기",
    Status.AWAITING_REVIEW: "🔍 검토 대기",
    Status.DONE: "✓ 완료",
    Status.REJECTED: "✗ 거절",
    Status.FAILED: "⚠ 실패",
    Status.CANCELLED: "— 취소",
}


_THUMB_SIZE = 96  # 가로 스트립 썸네일 한 변
_MAX_THUMBS = 6  # 그 이상은 +N 표시


class StageCard(QFrame):
    """1 단계 카드 — 풍성한 미리보기 + 산출물 클릭 → 뷰어."""

    artifact_clicked = Signal(object)  # ArtifactSummary

    def __init__(
        self,
        *,
        stage: Stage,
        is_current: bool,
        current_status: Status,
        artifacts: list[ArtifactSummary],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._stage = stage
        self._is_current = is_current
        self._artifacts = artifacts

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { padding: 10px 12px; "
            f"border: 1px solid {'#c4623c' if is_current else '#d9d0bc'}; "
            f"border-radius: 4px; "
            f"background: {'#fcf0e9' if is_current else '#ffffff'}; }}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # 헤더 — 단계 제목 + 상태 (현재 단계만 status hint 표시)
        header = QHBoxLayout()
        title = QLabel(_STAGE_LABEL[stage])
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        header.addWidget(title, stretch=1)

        if is_current:
            status_lbl = QLabel(_STATUS_HINT.get(current_status, ""))
            status_lbl.setStyleSheet(
                "color: #c4623c; font-size: 11px; font-weight: 600;"
            )
            header.addWidget(status_lbl)

        layout.addLayout(header)

        # 본문 — 산출물 미리보기
        body = self._build_body()
        if body is not None:
            layout.addWidget(body)
        elif not is_current:
            hint = QLabel("(대기)")
            hint.setStyleSheet("color: #7a756c; font-size: 11px;")
            layout.addWidget(hint)

    # ── 본문 빌드 ───────────────────────────────────────────────────────────

    def _build_body(self) -> QWidget | None:
        if not self._artifacts:
            return None

        # 단계별 분기
        if self._stage == Stage.IMAGE:
            return self._build_image_body()
        if self._stage in (Stage.TOPIC, Stage.DRAFT, Stage.HUMANIZE, Stage.PUBLISH):
            return self._build_text_body()
        return None

    def _build_image_body(self) -> QWidget:
        """IMAGE 단계 — 프롬프트 indicator + 썸네일 스트립."""
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        prompts = [a for a in self._artifacts if a.kind == "image_prompts"]
        images = [a for a in self._artifacts if a.kind == "image"]

        if prompts:
            count = self._count_prompt_items(prompts[-1].preview_text)
            line = QLabel(
                f"🎨 Claude 이미지 프롬프트 {count}개 생성됨 — 클릭하면 다이얼로그 열림"
                if count
                else "🎨 Claude 이미지 프롬프트 산출물 1개"
            )
            line.setStyleSheet("color: #4a4742; font-size: 11px;")
            line.mousePressEvent = lambda _e, a=prompts[-1]: self.artifact_clicked.emit(a)  # type: ignore[method-assign]
            line.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(line)

        if images:
            count_line = QLabel(f"📷 이미지 {len(images)}장")
            count_line.setStyleSheet(
                "color: #4a4742; font-size: 11px; font-weight: 600;"
            )
            layout.addWidget(count_line)

            strip = self._build_thumbnail_strip(images)
            layout.addWidget(strip)
        else:
            empty = QLabel("(아직 업로드된 이미지 없음)")
            empty.setStyleSheet("color: #7a756c; font-size: 11px;")
            layout.addWidget(empty)

        return wrapper

    def _build_thumbnail_strip(self, images: list[ArtifactSummary]) -> QWidget:
        """가로 스트립 — 최대 6장. 클릭 → ArtifactViewer."""
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        for img in images[:_MAX_THUMBS]:
            layout.addWidget(self._make_thumbnail(img))

        if len(images) > _MAX_THUMBS:
            more = QLabel(f"+{len(images) - _MAX_THUMBS} more")
            more.setStyleSheet(
                "color: #7a756c; padding: 0 8px; font-size: 11px; "
                "border: 1px dashed #d9d0bc; border-radius: 3px;"
            )
            more.setFixedHeight(_THUMB_SIZE)
            more.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(more)

        layout.addStretch(1)
        return wrapper

    def _make_thumbnail(self, artifact: ArtifactSummary) -> QLabel:
        thumb = QLabel()
        thumb.setFixedSize(_THUMB_SIZE, _THUMB_SIZE)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet(
            "QLabel { background: #f3efe5; border: 1px solid #d9d0bc; "
            "border-radius: 3px; }"
            "QLabel:hover { border-color: #c4623c; }"
        )
        thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        thumb.setToolTip(
            f"{artifact.abs_path.name}\n{artifact.size:,} bytes\n클릭하면 큰 이미지 보기"
        )

        try:
            pm = QPixmap(str(artifact.abs_path))
            if not pm.isNull():
                scaled = pm.scaled(
                    _THUMB_SIZE - 6,
                    _THUMB_SIZE - 6,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                thumb.setPixmap(scaled)
            else:
                thumb.setText("(read fail)")
        except Exception:  # noqa: BLE001
            thumb.setText("(error)")

        thumb.mousePressEvent = lambda _e, a=artifact: self.artifact_clicked.emit(a)  # type: ignore[method-assign]
        return thumb

    def _build_text_body(self) -> QWidget:
        """TOPIC/DRAFT/HUMANIZE/PUBLISH 단계 — 텍스트 미리보기."""
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # 가장 최근 텍스트 산출물 우선 (PUBLISH 면 .html, 그 외 .md/.json)
        text_artifacts = [a for a in self._artifacts if a.kind == "text"]
        if not text_artifacts:
            return wrapper

        latest = text_artifacts[-1]
        preview = (latest.preview_text or "").strip()

        # 단계별 미리보기 톤 — TOPIC 은 JSON 이라 lecture title 추출, 나머지는 raw 첫 줄
        rendered_preview = self._render_preview(latest)

        prev_lbl = QLabel()
        prev_lbl.setText(rendered_preview)
        prev_lbl.setWordWrap(True)
        prev_lbl.setTextFormat(Qt.TextFormat.RichText)
        prev_lbl.setStyleSheet(
            "QLabel { color: #0a0908; font-size: 11.5px; "
            "background: #fcfaf3; border: 1px solid #ebe4d2; "
            "padding: 8px; border-radius: 3px; }"
        )
        prev_lbl.setMaximumHeight(120)
        layout.addWidget(prev_lbl)

        # 메타 + 전체 보기 버튼
        meta_row = QHBoxLayout()
        meta_lbl = QLabel(
            f"{latest.size:,} bytes  ·  {latest.created_at.strftime('%H:%M:%S')}"
        )
        meta_lbl.setStyleSheet("color: #7a756c; font-size: 10px;")
        meta_row.addWidget(meta_lbl, stretch=1)

        view_btn = QPushButton("전체 보기")
        view_btn.setStyleSheet(
            "QPushButton { padding: 3px 10px; font-size: 10px; "
            "background: transparent; border: 1px solid #d9d0bc; border-radius: 2px; }"
            "QPushButton:hover { border-color: #c4623c; color: #c4623c; }"
        )
        view_btn.clicked.connect(lambda: self.artifact_clicked.emit(latest))
        meta_row.addWidget(view_btn)

        layout.addLayout(meta_row)
        return wrapper

    def _render_preview(self, artifact: ArtifactSummary) -> str:
        """단계별 미리보기 렌더 (HTML)."""
        text = (artifact.preview_text or "").strip()
        if not text:
            return "<i>(미리보기 비어있음)</i>"

        # TOPIC = JSON → lecture title 들 추출해서 번호 매기기
        if self._stage == Stage.TOPIC and artifact.rel_path.endswith(".json"):
            try:
                # preview 가 잘렸을 수 있어 partial JSON parse 시도 — 실패하면 raw
                parsed = json.loads(text + ("..." if artifact.is_text_truncated else ""))
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                title = parsed.get("series_title") or ""
                lectures = parsed.get("lectures") or []
                lines: list[str] = []
                if title:
                    lines.append(f"<b>📚 {escape(str(title))}</b>")
                if isinstance(lectures, list):
                    for lec in lectures[:6]:
                        if not isinstance(lec, dict):
                            continue
                        pos = lec.get("position", "?")
                        t = lec.get("title", "")
                        lines.append(f"  {pos}. {escape(str(t))}")
                    if len(lectures) > 6:
                        lines.append(f"  …외 {len(lectures) - 6}강")
                if lines:
                    return "<br>".join(lines)

        # 일반 텍스트 — 첫 5줄
        lines = [escape(line) for line in text.splitlines()[:5] if line.strip()]
        suffix = " <i>…</i>" if artifact.is_text_truncated else ""
        return "<br>".join(lines) + suffix

    @staticmethod
    def _count_prompt_items(preview: str | None) -> int:
        """image_prompts JSON preview 에서 ``images`` 배열 길이 추정."""
        if not preview:
            return 0
        try:
            data = json.loads(preview + "...")
            items = data.get("images") if isinstance(data, dict) else None
            return len(items) if isinstance(items, list) else 0
        except (json.JSONDecodeError, AttributeError):
            return 0
