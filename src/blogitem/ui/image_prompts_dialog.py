"""ImagePromptsDialog — Claude 가 생성한 이미지 프롬프트 N+1개를 리스트로 표시.

각 프롬프트마다 [클립보드 복사] + [ChatGPT 열기] 버튼. 사용자가 클릭 한 번으로
프롬프트를 ChatGPT 웹에 붙여넣어 이미지 생성.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

CHATGPT_URL = "https://chatgpt.com/"


_ROLE_LABEL = {
    "thumbnail": "🖼 썸네일",
    "body": "📄 본문",
}


def _format_role_label(item: dict[str, object]) -> str:
    """카드 헤더 라벨 — 시리즈 모드(lecture_position 있음) 우선, 없으면 강의 모드."""
    role = str(item.get("role") or "")
    lecture_pos = item.get("lecture_position")
    lecture_title = str(item.get("lecture_title") or "").strip()

    if role == "thumbnail":
        # 시리즈 썸네일 / 강의 썸네일 둘 다 같은 라벨
        return "🖼 시리즈 썸네일" if lecture_pos in (None, 0) else "🖼 썸네일"

    if role == "body":
        # 시리즈 단위 — "📚 N강 — title"
        if isinstance(lecture_pos, (int, float)) and lecture_pos:
            label = f"📚 {int(lecture_pos)}강"
            if lecture_title:
                label = f"{label} — {lecture_title}"
            return label
        # 강의 단위 (legacy) — "📄 본문 #N"
        position = item.get("position") or 0
        return f"📄 본문 #{position}"

    return role or "—"


class _PromptCard(QFrame):
    """단일 프롬프트 카드 — 역할/목적 + 프롬프트 textarea + 복사/열기/보내기 버튼."""

    send_to_chatgpt = Signal(str)  # prompt text

    def __init__(self, item: dict[str, object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { border: 1px solid #d9d0bc; border-radius: 4px; "
            "padding: 10px; background: #fff; }"
        )

        purpose = str(item.get("purpose") or "")
        prompt_text = str(item.get("prompt") or "")

        role_lbl_text = _format_role_label(item)

        header = QHBoxLayout()
        role_lbl = QLabel(f"<b>{role_lbl_text}</b>")
        role_lbl.setStyleSheet("font-size: 13px; color: #0a0908;")
        purpose_lbl = QLabel(purpose)
        purpose_lbl.setStyleSheet("color: #4a4742; font-size: 12px;")
        purpose_lbl.setWordWrap(True)
        header.addWidget(role_lbl)
        header.addStretch(1)

        self._editor = QPlainTextEdit()
        self._editor.setPlainText(prompt_text)
        self._editor.setStyleSheet(
            "QPlainTextEdit { font-family: 'JetBrains Mono', Consolas, monospace; "
            "font-size: 11px; background: #fcfaf3; border: 1px solid #ebe4d2; "
            "padding: 8px; }"
        )
        self._editor.setMinimumHeight(110)

        copy_btn = QPushButton("📋 복사")
        copy_btn.clicked.connect(self._copy)
        open_btn = QPushButton("🌐 외부 브라우저")
        open_btn.clicked.connect(self._open_chatgpt)
        send_btn = QPushButton("▶ 우측 ChatGPT 로 보내기")
        send_btn.setStyleSheet(
            "QPushButton { background: #c4623c; color: #fff; padding: 8px 14px; "
            "border-radius: 3px; font-weight: 600; }"
            "QPushButton:hover { background: #a85331; }"
        )
        send_btn.clicked.connect(self._send)

        action_row = QHBoxLayout()
        action_row.addWidget(copy_btn)
        action_row.addWidget(open_btn)
        action_row.addStretch(1)
        action_row.addWidget(send_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(header)
        layout.addWidget(purpose_lbl)
        layout.addWidget(self._editor)
        layout.addLayout(action_row)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._editor.toPlainText())

    def _open_chatgpt(self) -> None:
        QDesktopServices.openUrl(QUrl(CHATGPT_URL))

    def _send(self) -> None:
        """우측 임베디드 ChatGPT 패널로 프롬프트 전송 — 다이얼로그가 라우팅."""
        self.send_to_chatgpt.emit(self._editor.toPlainText())


class ImagePromptsDialog(QDialog):
    """이미지 프롬프트 다이얼로그.

    사용자 흐름:
        1. 다이얼로그 열림 → 카드 N+1 개 (썸네일 1 + 본문 N).
        2. [복사 + ChatGPT 열기] 클릭 → 프롬프트 클립보드 + 브라우저.
        3. ChatGPT 에 붙여넣고 이미지 생성 + 다운로드.
        4. 닫고 → blogitem 의 "다운로드 임포트" 또는 워치 폴더가 자동 감지.
    """

    def __init__(
        self,
        *,
        prompts_data: dict[str, object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Claude 이미지 프롬프트 + ChatGPT 듀얼 브라우저")
        self.setMinimumSize(1480, 880)
        # 보낸 횟수 — 짝/홀로 패널 1, 2 round-robin
        self._send_counter = 0

        # 헤더 — 스타일 가이드
        style_guide = str(prompts_data.get("style_guide") or "")
        header_lbl = QLabel(
            f"<b>스타일 가이드:</b> {style_guide}" if style_guide else
            "Claude 가 생성한 이미지 프롬프트입니다 — 각 프롬프트를 ChatGPT 에 붙여넣어 이미지를 만드세요."
        )
        header_lbl.setWordWrap(True)
        header_lbl.setStyleSheet(
            "padding: 10px; background: #ebe4d2; color: #0a0908; "
            "border-radius: 3px; font-size: 12px;"
        )

        # 카드 스택
        cards_container = QWidget()
        cards_layout = QVBoxLayout(cards_container)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(8)

        items = prompts_data.get("images") or []
        if isinstance(items, list):
            # 썸네일 먼저, 그다음 본문 — lecture_position(시리즈 모드) 또는
            # position(강의 모드) 오름차순.
            def _sort_key(it: dict[str, object]) -> tuple[int, int]:
                is_thumb = 0 if it.get("role") == "thumbnail" else 1
                lec_pos = it.get("lecture_position")
                if isinstance(lec_pos, (int, float)) and lec_pos:
                    return (is_thumb, int(lec_pos))
                return (is_thumb, int(it.get("position") or 0))

            sorted_items = sorted(
                (i for i in items if isinstance(i, dict)),
                key=_sort_key,
            )
            for item in sorted_items:
                card = _PromptCard(item)
                card.send_to_chatgpt.connect(self._on_send_to_chatgpt)
                cards_layout.addWidget(card)
        else:
            cards_layout.addWidget(QLabel("(이미지 프롬프트가 없습니다 — 응답 형식 확인 필요)"))

        # raw 폴백 표시
        if "raw" in prompts_data:
            raw_label = QLabel("<b>원본 응답 (JSON 파싱 실패):</b>")
            raw_text = QPlainTextEdit(str(prompts_data.get("raw") or ""))
            raw_text.setReadOnly(True)
            raw_text.setMaximumHeight(180)
            cards_layout.addWidget(raw_label)
            cards_layout.addWidget(raw_text)

        cards_layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(cards_container)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        # ── 좌측: 프롬프트 카드 / 우측: 임베디드 ChatGPT 브라우저 ──────────────
        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)
        left_layout.addWidget(scroll)

        # 우측: 두 개의 ChatGPT 패널 (수직 분할) — 같은 로그인 프로필 공유, 독립 탭
        panel_1 = _ChatGPTPanel(slot_label="1", parent=self)
        panel_2 = _ChatGPTPanel(slot_label="2", parent=self)
        self._chatgpt_panels = [panel_1, panel_2]

        right_split = QSplitter(Qt.Orientation.Vertical, self)
        right_split.setChildrenCollapsible(False)
        right_split.addWidget(panel_1)
        right_split.addWidget(panel_2)
        right_split.setSizes([400, 400])

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_split)
        splitter.setSizes([460, 1020])

        # 닫기
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(header_lbl)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(buttons)

    # ── 카드 → 패널 라우팅 ──────────────────────────────────────────────────

    def _on_send_to_chatgpt(self, text: str) -> None:
        """카드의 [▶ 보내기] 신호 — 두 패널 round-robin 으로 분배.

        n번째 클릭 → 패널 (n % 2 + 1). 두 채팅을 병렬로 활용해 대기 시간 절반.
        """
        panels = getattr(self, "_chatgpt_panels", None)
        if not panels:
            return
        idx = self._send_counter % len(panels)
        panels[idx].send_prompt(text)
        self._send_counter += 1


class _ChatGPTPanel(QWidget):
    """우측 임베디드 브라우저 — chatgpt.com.

    - QWebEngineProfile 영구 프로필: 로그인 한 번 → 다음 실행에서도 유지.
    - 상단 툴바: 뒤/앞/새로고침 + 주소 표시 + 새 대화 버튼.
    """

    # 같은 로그인 프로필을 두 인스턴스가 공유 — 클래스 레벨 캐시.
    _shared_profile: object | None = None

    def __init__(
        self,
        *,
        slot_label: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._slot_label = slot_label

        # WebEngine import 는 런타임에만 — 미설치/오류 환경에서도 다이얼로그 자체는 뜸
        try:
            from PySide6.QtWebEngineCore import QWebEngineProfile
            from PySide6.QtWebEngineWidgets import QWebEngineView
        except ImportError as e:  # pragma: no cover — 패키지 누락 환경
            err = QLabel(f"(브라우저 컴포넌트 로드 실패: {e})")
            err.setWordWrap(True)
            err.setStyleSheet("padding: 12px; color: #c4623c;")
            box = QVBoxLayout(self)
            box.addWidget(err)
            self._view = None
            return

        # 영구 프로필 — 로그인/쿠키 유지. 모든 패널 인스턴스가 공유 (같은 계정).
        if _ChatGPTPanel._shared_profile is None:
            profile_root = Path.home() / ".blogitem" / "webengine"
            profile_root.mkdir(parents=True, exist_ok=True)
            shared = QWebEngineProfile("blogitem-chatgpt")
            shared.setPersistentStoragePath(str(profile_root / "storage"))
            shared.setCachePath(str(profile_root / "cache"))
            shared.setHttpUserAgent(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
            _ChatGPTPanel._shared_profile = shared
        profile = _ChatGPTPanel._shared_profile
        self._view = QWebEngineView(self)
        from PySide6.QtWebEngineCore import QWebEnginePage

        self._view.setPage(QWebEnginePage(profile, self._view))
        self._view.setUrl(QUrl(CHATGPT_URL))

        # 툴바 — 슬롯 라벨 (패널 1/2 구분 배지)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 4, 4, 4)
        toolbar.setSpacing(4)

        if self._slot_label:
            badge = QLabel(self._slot_label)
            badge.setStyleSheet(
                "QLabel { background: #c4623c; color: #fff; "
                "min-width: 24px; padding: 4px 8px; "
                "border-radius: 12px; font-weight: 700; font-size: 12px; "
                "qproperty-alignment: AlignCenter; }"
            )
            toolbar.addWidget(badge)

        back_btn = QPushButton("◀")
        fwd_btn = QPushButton("▶")
        reload_btn = QPushButton("⟳")
        home_btn = QPushButton("🏠 ChatGPT")
        for b in (back_btn, fwd_btn, reload_btn, home_btn):
            b.setStyleSheet(
                "QPushButton { padding: 4px 10px; font-size: 12px; "
                "background: transparent; border: 1px solid #d9d0bc; border-radius: 3px; }"
                "QPushButton:hover { border-color: #c4623c; color: #c4623c; }"
            )

        back_btn.clicked.connect(self._view.back)
        fwd_btn.clicked.connect(self._view.forward)
        reload_btn.clicked.connect(self._view.reload)
        home_btn.clicked.connect(lambda: self._view.setUrl(QUrl(CHATGPT_URL)))

        self._url_label = QLabel(CHATGPT_URL)
        self._url_label.setStyleSheet(
            "QLabel { color: #4a4742; font-size: 11px; "
            "padding: 4px 8px; background: #fcfaf3; "
            "border: 1px solid #ebe4d2; border-radius: 3px; }"
        )
        self._url_label.setWordWrap(False)
        self._view.urlChanged.connect(
            lambda u: self._url_label.setText(u.toString()[:120])
        )

        toolbar.addWidget(back_btn)
        toolbar.addWidget(fwd_btn)
        toolbar.addWidget(reload_btn)
        toolbar.addWidget(self._url_label, stretch=1)
        toolbar.addWidget(home_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(toolbar)
        layout.addWidget(self._view, stretch=1)

    def send_prompt(self, text: str) -> None:
        """프롬프트를 ChatGPT 입력창에 자동 입력 후 전송.

        ChatGPT 의 입력 위젯이 ProseMirror contenteditable 이라 단순 value
        설정으론 React state 갱신이 안 됨 → ``execCommand('insertText')`` 사용.
        실패 폴백: textarea / contenteditable 직접 set + input 이벤트 dispatch.
        전송: ``[data-testid="send-button"]`` 또는 ``button[aria-label*="Send"]``.

        프롬프트 앞에 이미지 생성 명시적 지시문을 자동 추가 — 그냥 묘사만 보내면
        ChatGPT 가 채팅으로 답변하는 경우가 있어서.
        """
        if self._view is None:
            return

        # 이미지 생성 강제 헤더 prepend
        directive = (
            "위 프롬프트로 이미지 1장을 만들어주세요. "
            "1024x1024 PNG, 추가 설명 없이 이미지만 출력.\n\n"
            "---\n\n"
        )
        text = directive + text

        # 클립보드에도 복사 — 자동 입력 실패 시 사용자가 Ctrl+V 로 폴백 가능
        QGuiApplication.clipboard().setText(text)

        # JS 문자열 안전하게 직렬화
        import json as _json

        js_text = _json.dumps(text)
        script = f"""
        (function() {{
            const text = {js_text};
            // 1) ProseMirror contenteditable 우선
            let editor =
                document.querySelector('#prompt-textarea')
                || document.querySelector('div[contenteditable="true"][role="textbox"]')
                || document.querySelector('div[contenteditable="true"]')
                || document.querySelector('textarea');
            if (!editor) return 'no_editor';

            editor.focus();

            // contenteditable 분기
            if (editor.getAttribute && editor.getAttribute('contenteditable') === 'true') {{
                try {{
                    document.execCommand('selectAll', false, null);
                    document.execCommand('insertText', false, text);
                }} catch (e) {{
                    // 폴백 — innerText + input 이벤트
                    editor.innerText = text;
                    editor.dispatchEvent(new InputEvent('input', {{bubbles:true}}));
                }}
            }} else {{
                // textarea
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                setter.call(editor, text);
                editor.dispatchEvent(new Event('input', {{bubbles:true}}));
            }}

            // 2) 전송 버튼 클릭 — 약간 지연 (React 상태 업데이트 대기)
            setTimeout(() => {{
                const btn =
                    document.querySelector('[data-testid="send-button"]')
                    || document.querySelector('button[aria-label*="Send"]')
                    || document.querySelector('button[aria-label*="전송"]');
                if (btn && !btn.disabled) {{ btn.click(); }}
            }}, 250);

            return 'ok';
        }})();
        """
        self._view.page().runJavaScript(script)
