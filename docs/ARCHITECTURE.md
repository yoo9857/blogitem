# blogitem — Architecture

> 본 문서는 의사결정 기록(ADR) + 도메인 모델 + 운영 흐름을 정리한다.
> 코드와 다를 경우 코드가 진리(source of truth) — 문서는 코드 변경 시 같이 갱신.

---

## 1. 파이프라인 흐름

```
1. TOPIC      Claude 가 강의/주제·커리큘럼 결정 (자동)
   ↓
2. IMAGE      ChatGPT 웹에서 사람이 작업 → 드래그앤드롭 업로드 (반자동)
   ↓
3. DRAFT      Claude 가 초고 작성 (자동)
   ↓
4. HUMANIZE   ChatGPT 웹에서 사람이 SEO·톤 재구성 → 업로드 (반자동)
   ↓
5. CONFIRM    diff view 에서 사람 검수 (수동 게이트)
   ↓
6. PUBLISH    Claude 가 텍스트·이미지 균등 분할 후 네이버 블로그 게시 (자동)
```

---

## 2. 도메인 모델

| 테이블 | 설명 |
|---|---|
| `series` | 강의/시리즈 — 1 시리즈 = N 파이프라인 |
| `pipelines` | 1 블로그 글 = 6 단계 흐름 단위 |
| `pipeline_stages` | 단계별 진행 기록 (감사 추적) |
| `artifacts` | 산출물 메타 (실파일은 디스크) |
| `approvals` | 사람 컨펌 결정 + 사유 |

상세는 `src/blogitem/pipeline/models.py`.

상태 머신은 `src/blogitem/pipeline/state_machine.py` — 잘못된 전이는 `InvalidTransitionError`.

---

## 3. 외부 의존성

| 의존성 | 사용 위치 | 인증 |
|---|---|---|
| Anthropic Claude API | TOPIC / DRAFT / PUBLISH | API key (keyring) |
| 네이버 블로그 API | PUBLISH | OAuth 2.0 (refresh_token in keyring) |
| ChatGPT 웹 (사람 작업) | IMAGE / HUMANIZE | 사용자 ChatGPT 구독 |

---

## 4. 보안

- 모든 시크릿 → `keyring` (Windows Credential Manager)
- OAuth 콜백 → 임시 `127.0.0.1:8765` HTTP 서버 (PKCE)
- 단일 인스턴스 → `QLockFile` (게시 중복 방지)
- 시크릿은 예외 메시지·로그에 절대 노출하지 않음

---

## 5. 빌드 우선순위

| 단계 | 내용 |
|---|---|
| **P0** | Bootstrap, MainWindow, SettingsDialog, DB 마이그레이션 |
| **P1** | 네이버 OAuth + Blog API + Worker — 텍스트 입력만으로 게시 가능 (E2E) |
| **P2** | Pipeline / Stage 모델 + ArtifactStore + 빈 파이프라인 생성 UI |
| **P3** | Claude SDK + Orchestrator + 자동 단계(TOPIC/DRAFT/PUBLISH) 가동 |
| **P4** | UploadDialog (드래그앤드롭) + DiffView + ConfirmDialog |
| **P5** | Watchdog + Notifier (정체 알림 / 토큰 만료 알림) |
| **P6** | EmailToBlogChannel 폴백 |

---

## 6. 미해결 결정

- alembic 마이그레이션 — 첫 마이그레이션 자동 생성 시점 (P0 진입 시)
- DB 백업/복원 정책 — SQLite 파일 단순 복사 vs 정기 dump
- PyInstaller `.exe` 빌드 — 코드 서명 (Windows SmartScreen 회피) 적용 여부
