# blogitem

**AI 멀티-스텝 콘텐츠 파이프라인 데스크톱 앱.**

Claude → ChatGPT(웹수동) → Claude → ChatGPT(웹수동) → 사람 컨펌 → 네이버 블로그 게시.
Python 3.11+ · PySide6 · SQLite · 단일 실행 파일 (`.exe`) 배포 가능.

> 웹사이트가 아닙니다. 사용자 PC 에서 실행되는 네이티브 데스크톱 소프트웨어.

---

## 파이프라인

```
1. 주제 결정    Claude 가 강의/콘텐츠 커리큘럼 설계 (자동)
   ↓
2. 이미지 생성   ChatGPT 웹에서 사람이 작업 → blogitem 에 업로드 (수동)
   ↓
3. 초고 작성    Claude 가 본문 전문화 (자동)
   ↓
4. 인간화       ChatGPT 웹에서 사람이 SEO·톤 재구성 → 업로드 (수동)
   ↓
5. 컨펌        diff view 에서 사람 검수 (게이트)
   ↓
6. 게시        Claude 가 이미지·본문 균등 분할 후 네이버 블로그 게시 (자동)
```

---

## 기술 스택

| 영역 | 선택 |
|---|---|
| 언어 | Python 3.11+ |
| 패키지 매니저 | `uv` |
| GUI | **PySide6** (Qt 6) |
| 비동기 | `QThread` + Signals/Slots |
| ORM | SQLAlchemy 2.x + Alembic |
| DB | SQLite (`data/blogitem.db`) |
| LLM | `anthropic` 공식 SDK |
| HTTP | `httpx` |
| 시크릿 | **`keyring`** (Windows Credential Manager) |
| 설정 | `pydantic-settings` |
| 로깅 | `structlog` (NDJSON) |
| 테스트 | `pytest` + `pytest-qt` |
| Lint+Format | `ruff` |
| 타입 | `mypy --strict` |
| 배포 | `PyInstaller` 단일 `.exe` |

---

## 설치 / 실행

### 사전 요구사항

- Python 3.11 이상
- `uv` ([설치](https://docs.astral.sh/uv/getting-started/installation/))

### 개발 환경 셋업

```powershell
git clone https://github.com/yoo9857/blogitem.git
cd blogitem
uv venv
uv sync --extra dev
cp .env.example .env

# 시크릿(Anthropic API 키, 네이버 OAuth client_secret)은 keyring 에 저장.
# 최초 GUI 실행 후 설정 다이얼로그에서 입력.
```

### 실행

```powershell
uv run blogitem                     # GUI 시작
uv run pytest                       # 테스트
uv run ruff check .                 # 린트
uv run ruff format .                # 포맷
uv run mypy src                     # 타입체크
```

### 단일 `.exe` 빌드

```powershell
uv sync --extra build
.\scripts\build_exe.ps1
# → dist\blogitem.exe
```

---

## 디렉토리 구조

```
blogitem/
├── src/blogitem/                # 패키지
│   ├── __main__.py              # GUI 진입점
│   ├── config.py                # pydantic-settings
│   ├── db.py                    # SQLAlchemy
│   ├── log.py                   # structlog
│   ├── secrets.py               # keyring 래퍼
│   ├── pipeline/                # 도메인 로직 (UI 무관)
│   ├── ai/                      # LLM 클라이언트 + 프롬프트
│   ├── channels/                # PublishChannel (네이버, 폴백)
│   ├── naver/                   # OAuth + Blog API
│   ├── queue/                   # 작업 큐 + 워커
│   ├── watchdog/                # 정체 감지 + 토큰 만료 모니터
│   ├── notify/                  # OS 알림 + SMTP
│   └── ui/                      # PySide6 위젯·화면
├── migrations/                  # alembic
├── tests/                       # pytest
├── data/                        # gitignored — SQLite + artifacts
├── tokens/                      # gitignored — keyring 폴백
├── logs/                        # gitignored
├── docs/                        # ARCHITECTURE / SETUP / PROMPTS
└── scripts/                     # 빌드·운영 스크립트
```

---

## 보안 원칙

- API 키 / OAuth client_secret / refresh_token → **`keyring` 사용**, 파일·env·DB 평문 저장 금지
- OAuth 인증 — 임시 localhost (127.0.0.1:8765) HTTP 콜백 + PKCE
- 단일 인스턴스 보장 — `QLockFile` (게시 중복 방지)
- 시크릿은 예외 메시지·로그에 절대 포함하지 않음 (`anthropic.AuthenticationError` 등 예외 핸들러에서 마스킹)

---

## 상태

🟡 초기 스캐폴드 — 패키지 구조 + 도구 체인. 도메인 코드는 후속 커밋.

내부 사용. 외부 배포 금지.
