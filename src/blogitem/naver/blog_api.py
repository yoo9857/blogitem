"""네이버 블로그 글쓰기 API 클라이언트.

엔드포인트: ``POST https://openapi.naver.com/blog/writePost.json``
인증:        ``Authorization: Bearer {access_token}``
요청 형식:   ``application/x-www-form-urlencoded``

요청 파라미터:
    - title (필수)
    - contents (필수, HTML)
    - categoryNo (선택)
    - tags (선택, 쉼표 구분)

P1 — 본격 구현 (httpx + 재시도 정책).
"""

from __future__ import annotations


WRITE_POST_URL = "https://openapi.naver.com/blog/writePost.json"


class BlogApi:
    """네이버 블로그 API 호출."""

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
        """블로그 글 게시. 성공 시 logNo 반환.

        Raises:
            BlogApiError: 4xx 영구 실패 또는 재시도 한도 초과.
        """
        raise NotImplementedError("P1 — httpx POST 구현 필요")


class BlogApiError(RuntimeError):
    """네이버 블로그 API 호출 실패."""

    def __init__(self, message: str, *, status_code: int, retryable: bool) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
