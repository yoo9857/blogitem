# blogitem — 사용 가이드

> 처음 시작 → 첫 게시까지 단계별 안내. dry_run 모드로 안전하게 시작 추천.

---

## 1. 환경 준비 (한 번만)

```powershell
# uv 설치
winget install --id=astral-sh.uv -e --source winget

# 의존성 + 가상환경
cd C:\blogitem
uv sync --extra dev
```

### LLM CLI 인증 (둘 중 하나)

API 비용 0 으로 사용하려면 CLI 인증 필요:

```powershell
# Anthropic Claude (Max 구독)
claude /login

# OpenAI Codex (ChatGPT Plus)
codex login
```

### `.env` 파일

```env
BLOGITEM_LOG_LEVEL=info
BLOGITEM_DB_PATH=./data/blogitem.db
BLOGITEM_ARTIFACTS_DIR=./data/artifacts
BLOGITEM_DRY_RUN=true                    # ← 실제 게시 차단 (셋업 단계 권장)

# LLM 모드 (api / claude_cli / codex_cli)
BLOGITEM_LLM_MODE=claude_cli

# Orchestrator (자동 advance)
BLOGITEM_ORCHESTRATOR_ENABLED=false       # 처음엔 끄고 수동으로 단계별 확인

# 워치 폴더 (ChatGPT 다운로드 자동 감지)
BLOGITEM_IMAGE_WATCH_DIR=                 # 빈 값 → ~/Downloads
BLOGITEM_IMAGE_WATCH_WINDOW_MIN=120
```

---

## 2. 앱 실행

```powershell
uv run blogitem
```

첫 실행 시:
- Alembic 마이그레이션 자동 실행 → SQLite DB 생성
- 메인 윈도우 열림 + 하단 터미널 도크 (Ctrl+` 토글)

### 설정 (Anthropic API · 네이버 OAuth)

메뉴 → 설정 → 탭별로 입력. CLI 모드면 Anthropic API 키 불필요.
네이버 게시는 OAuth 2.0 인증 필요 — `네이버` 탭에서 client_id/secret 입력 후 [네이버 연결].

---

## 3. 첫 시리즈 만들기

**파일 → 새 시리즈 (Ctrl+N)**

- 주제: 예) `C언어 입문 5강 완벽한 커리큘럼`
- 강의 수: `5` (테스트 단계 — 작게 시작)

→ 좌측 목록에 #1~#5 파이프라인 5개 생성됨. 모두 TOPIC/PENDING 상태.

---

## 4. 단계별 진행 (수동)

### 4-1. TOPIC — 주제·커리큘럼 (Claude 자동)

좌측 #1 선택 → 우측에 단계 카드 → **"주제 생성 (Claude)"** 버튼.

→ 하단 터미널에 Claude 실시간 응답 스트리밍.
→ 완료 시 IMAGE/AWAITING_INPUT 으로 자동 전이.

산출물: `data/artifacts/{YYYY}/{MM}/{pipeline_id}/text/*.json` (커리큘럼 JSON)

### 4-2. IMAGE — 이미지 (반자동)

IMAGE 단계 액션 4개:

1. **🎨 프롬프트 생성 (Claude)** — Claude 가 강의 메타 → 썸네일 1 + 본문 N 프롬프트 생성
2. 다이얼로그에서 각 프롬프트 카드의 **[복사 + ChatGPT 열기]** 클릭
3. ChatGPT 웹에 자동 붙여넣기 → 이미지 생성 → 다운로드
4. blogitem 으로 돌아와 **📥 다운로드 임포트** → 워치 폴더(`~/Downloads`) 의 최근 이미지 썸네일 표시 → 다중 선택 → [선택 임포트]
5. 또는 **이미지 업로드…** (직접 드래그앤드롭/파일 선택)
6. 모두 끝나면 **다음 단계로 →**

### 4-3. DRAFT — 초고 (Claude 자동)

**"초고 작성 (Claude)"** 버튼 → Claude 가 1단계 산출물 + 이미지 메타 사용해 Markdown 초고 작성.
→ 완료 시 HUMANIZE/AWAITING_INPUT 으로 전이.

### 4-4. HUMANIZE — 인간화 (수동)

ChatGPT 웹에서 3단계 산출물(`data/artifacts/.../text/*.md`)을 복사해 가져와 인간화 처리 (반말 X, 강사 톤, SEO).

→ blogitem 으로 돌아와 **"인간화 본문 업로드…"** → 텍스트 붙여넣기 → 저장.
→ CONFIRM/AWAITING_REVIEW 으로 전이.

### 4-5. CONFIRM — 컨펌 (수동 게이트)

**"컨펌 (DiffView)…"** 클릭 → 좌(3.초고) vs 우(4.인간화) side-by-side diff.

- ✓ **승인** → PUBLISH/PENDING 전이
- ✗ **거절 + 사유 입력** → HUMANIZE/AWAITING_INPUT 회귀 (재업로드)

### 4-6. PUBLISH — 게시 (Claude + Naver 자동)

**"HTML 변환 + 게시 (Claude + 네이버)"** 클릭.

흐름:
1. Claude 가 HUMANIZE Markdown → 네이버 블로그용 HTML 변환
2. 이미지 N장 → `uploadPhoto.json` 으로 네이버 업로드 → URL 매핑
3. HTML 의 `<img src="...">` 를 네이버 URL 로 자동 치환
4. `writePost.json` 으로 게시 → logNo 응답
5. DONE 상태로 전이

> `dry_run=true` 면 실제 게시 안 됨 (확인 후 `false` 로 전환).

---

## 5. Orchestrator (자동 advance)

검증 끝났으면 자동화:

```env
BLOGITEM_ORCHESTRATOR_ENABLED=true
BLOGITEM_ORCHESTRATOR_INTERVAL_MIN=5
```

앱 재시작 → 자동 단계(TOPIC/DRAFT/PUBLISH) 가 PENDING 상태일 때 자동 실행.
사람 게이트(IMAGE/HUMANIZE/CONFIRM)는 그대로 사용자 입력 대기.

---

## 6. 모니터링

- **하단 터미널** — CLI subprocess 라인별 실시간 출력 + 턴 구분선 + 저장 버튼.
  `보기 → 터미널 표시/숨김` (Ctrl+`).
- **상태바** — `dry_run` ON/OFF, 큐 상태, 토큰 만료 일수.
- **Watchdog** (1시간 주기) — 24h 정체 파이프라인 + refresh_token 30일 임박 시 OS 알림.
- **로그 파일** — `logs/blogitem.log` (NDJSON, 5MB×3 회전).

---

## 7. 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| 앱 안 뜸 | `uv run blogitem` 실행 후 로그 확인 — `logs/blogitem.log` 의 ERROR 라인 |
| Claude 호출 실패 — API 키 | CLI 모드면 `claude /login` 한 번. API 모드면 [설정] 에서 키 입력 |
| 네이버 OAuth — 콜백 포트 점유 | `127.0.0.1:8765` 다른 프로세스 종료. `BLOGITEM_OAUTH_CALLBACK_PORT` 변경 가능하나 네이버 등록값과 일치 필요 |
| 토큰 만료 (refresh_token 1년) | [설정 → 네이버] 의 [토큰 폐기] → 다시 [네이버 연결] |
| 글쓰기 API 권한 거절 | 네이버 개발자센터에서 글쓰기 권한 신청 필요. 또는 SMTP 메일 발행 폴백 (`BLOGITEM_SMTP_*`) |
| 단계 실패 (FAILED) | 현재 UI 에서 재큐잉 미지원 — DB 직접 수정 또는 Orchestrator 토글 |
| 이미지 src 치환 안 됨 | Claude HTML 의 src 가 절대 경로인지 확인. 상대 경로면 `_rewrite_image_srcs` 매칭 실패 |

---

## 8. 빌드 / 배포

```powershell
# 단일 .exe 생성 (PyInstaller)
uv sync --extra build
.\scripts\build_exe.ps1
# → dist\blogitem.exe
```

코드 서명 X — Windows SmartScreen 경고 가능. 자체 사용은 OK.
