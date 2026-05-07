# blogitem

네이버 블로그 자동 게시 시스템.

블로그 글 메타를 큐잉 → cron 워커가 OAuth 2.0 인증으로 네이버 블로그 API 호출 → 자동 발행.
PHP 8.2 + MariaDB 10.x · cafe24 공유호스팅 호환 (FTP 업로드만으로 동작).

---

## 아키텍처 개요

- **큐 기반** — `blog_queue` 테이블에 멱등키(`blog:{slug}:v1`)로 enqueue
- **상태머신** — pending → processing → posted / failed (재시도 5회 + 지수 백오프)
- **OAuth 2.0** — `tokens/tokens.json` 에 refresh_token 보관 (config.php 와 분리)
- **dry_run 기본 ON** — 셋업 단계에서 실제 발행 없이 큐 흐름만 검증
- **외부 HTTP 격리** — `public/` 만 노출, `src/` `bin/` `tokens/` `logs/` 는 `.htaccess` deny

---

## 설치 (요약)

1. 네이버 개발자센터 앱 등록 → Client ID/Secret 발급, Callback URL 등록
2. DB 마이그레이션 실행
3. `config.sample.php` → `config.php` 복사 후 자격증명 입력
4. 어드민 페이지 → "네이버 연결" → OAuth 동의 → 토큰 자동 저장
5. cron 등록 (`bin/worker.php`, `bin/enqueue.php`)

상세 절차는 [docs/SETUP.md](docs/SETUP.md) 참조 (작성 예정).

---

## 디렉토리 구조 (계획)

```
blogitem/
├── public/              # 외부 노출 진입점 (admin, OAuth callback)
├── src/                 # 라이브러리 (외부 차단)
├── bin/                 # CLI cron 진입점
├── migrations/          # DB 스키마
├── docs/                # 운영 문서
├── tokens/              # gitignored · refresh_token 보관
├── logs/                # gitignored · NDJSON 런타임 로그
├── config.sample.php
└── config.php           # gitignored
```

---

## 보안 원칙

- `config.php` / `tokens/*` 는 `.gitignore` 강제
- 운영 시 `tokens/` chmod 700, 파일 600
- 어드민 — HTTP Basic Auth + bcrypt + IP 실패 카운터 + CSRF 1회용 토큰
- API Secret · refresh_token 은 예외/로그 본문에 절대 포함하지 않음

---

## 상태

🟡 초기 스캐폴드 — 실제 코드는 후속 커밋에서 추가.

내부 사용. 외부 배포 금지.
