"""네이버 블로그 글쓰기 API 클라이언트.

엔드포인트: ``POST https://openapi.naver.com/blog/writePost.json``
인증:        ``Authorization: Bearer {access_token}``
요청 형식:   ``application/x-www-form-urlencoded``

요청 파라미터:
    - title (필수)
    - contents (필수, HTML)
    - categoryNo (선택)
    - tags (선택, 쉼표 구분)

응답 (성공):
    ``{"result": {"logNo": "..."}, "message": {"@type":"...", "result": {"resultCode":"00", ...}}}``

에러 분기:
    - 401 → 영구 실패 (재인증 필요) — 호출 측이 refresh 후 재시도
    - 403 → 영구 실패 (권한 부족 — 글쓰기 API 미승인일 수 있음)
    - 5xx → 재시도 가능
    - 네트워크 timeout → 재시도 가능
"""

from __future__ import annotations

from typing import Final

import httpx

WRITE_POST_URL: Final = "https://openapi.naver.com/blog/writePost.json"
_TIMEOUT_SEC: Final = 20


class BlogApiError(RuntimeError):
    """네이버 블로그 API 호출 실패."""

    def __init__(self, message: str, *, status_code: int, retryable: bool) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class BlogApi:
    """네이버 블로그 글쓰기 API.

    한 인스턴스 = 한 access_token. 만료되면 새 인스턴스를 생성하는 패턴 (단순화).
    """

    def __init__(self, access_token: str) -> None:
        if not access_token:
            raise ValueError("access_token required")
        self._access_token = access_token

    def write_post(
        self,
        *,
        title: str,
        contents_html: str,
        category_no: int | None = None,
        tags: list[str] | None = None,
    ) -> str:
        """블로그 글 게시. 성공 시 ``logNo`` 문자열 반환.

        Raises:
            BlogApiError: 4xx 영구 실패 또는 5xx/timeout 재시도 가능 실패.
            ValueError: title/contents_html 비어 있음.
        """
        if not title:
            raise ValueError("title required")
        if not contents_html:
            raise ValueError("contents_html required")

        data: dict[str, str] = {
            "title": title,
            "contents": contents_html,
        }
        if category_no is not None:
            data["categoryNo"] = str(category_no)
        if tags:
            # 네이버 정책 — 태그는 ``,`` 구분, 각 태그 길이 제약은 콘솔 별도.
            data["tags"] = ",".join(t.strip() for t in tags if t.strip())

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        try:
            resp = httpx.post(
                WRITE_POST_URL,
                data=data,
                headers=headers,
                timeout=_TIMEOUT_SEC,
            )
        except httpx.TimeoutException as e:
            raise BlogApiError("network: timeout", status_code=0, retryable=True) from e
        except httpx.RequestError as e:
            raise BlogApiError(
                f"network: {type(e).__name__}", status_code=0, retryable=True
            ) from e

        if resp.status_code == 401:
            raise BlogApiError("unauthorized", status_code=401, retryable=False)
        if resp.status_code == 403:
            raise BlogApiError(
                "forbidden — 글쓰기 API 권한 없음 가능",
                status_code=403,
                retryable=False,
            )
        if resp.status_code == 429:
            raise BlogApiError("rate limited", status_code=429, retryable=True)
        if resp.status_code >= 500:
            raise BlogApiError(
                f"server error HTTP {resp.status_code}",
                status_code=resp.status_code,
                retryable=True,
            )
        if resp.status_code != 200:
            raise BlogApiError(
                f"HTTP {resp.status_code}: {_truncate(resp.text)}",
                status_code=resp.status_code,
                retryable=False,
            )

        try:
            body = resp.json()
        except ValueError as e:
            raise BlogApiError(
                "non-JSON response", status_code=200, retryable=False
            ) from e

        result = body.get("result") or {}
        log_no = result.get("logNo")
        if not log_no:
            # message 안의 resultCode 가 00 이 아니면 실패로 처리
            message = body.get("message") or {}
            inner = message.get("result") or {}
            code = str(inner.get("resultCode", "?"))
            text = str(inner.get("resultMessage", "no logNo"))
            raise BlogApiError(
                f"naver: {code} {text}",
                status_code=200,
                retryable=False,
            )
        return str(log_no)


def _truncate(s: str, limit: int = 200) -> str:
    """예외 메시지용 응답 본문 잘라내기 — secret leak 방지 + 가독성."""
    if len(s) <= limit:
        return s
    return s[:limit] + "…"
