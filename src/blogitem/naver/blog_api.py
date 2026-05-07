"""네이버 블로그 글쓰기 / 사진 업로드 API 클라이언트.

엔드포인트:
    - ``POST https://openapi.naver.com/blog/writePost.json`` — 글 게시 (form-encoded)
    - ``POST https://openapi.naver.com/blog/uploadPhoto.json`` — 사진 업로드 (multipart)
인증: ``Authorization: Bearer {access_token}``

응답 (writePost 성공):
    ``{"result": {"logNo": "..."}, "message": {"result": {"resultCode":"00", ...}}}``

응답 (uploadPhoto 성공):
    ``{"result": [{"url": "https://...", "fileSize": ...}]}``  (V1 — 단일 이미지)
    실제 응답 구조는 단수/복수 형태 모두 처리.

에러 분기:
    - 401 → 영구 (재인증 필요)
    - 403 → 영구 (권한 부족)
    - 429 → 재시도
    - 5xx / 네트워크 timeout → 재시도
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import httpx

WRITE_POST_URL: Final = "https://openapi.naver.com/blog/writePost.json"
UPLOAD_PHOTO_URL: Final = "https://openapi.naver.com/blog/uploadPhoto.json"
_TIMEOUT_SEC: Final = 20
_UPLOAD_TIMEOUT_SEC: Final = 60  # 업로드는 더 길게


_IMAGE_MIME_BY_EXT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def _guess_image_mime(path: Path) -> str:
    return _IMAGE_MIME_BY_EXT.get(path.suffix.lower(), "application/octet-stream")


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

    # ── 사진 업로드 (P11) ───────────────────────────────────────────────────

    def upload_photo(self, image_path: Path) -> str:
        """이미지 1장 업로드 → 네이버 호스팅 URL 반환 (HTML <img src> 에 사용).

        Args:
            image_path: 디스크의 이미지 파일 (PNG/JPG/JPEG/WebP/GIF/BMP).

        Returns:
            네이버 호스팅 URL 문자열 (https 시작).

        Raises:
            BlogApiError: 4xx 영구 / 5xx·timeout 재시도 가능.
            FileNotFoundError: 이미지 파일이 디스크에 없음.
            ValueError: 빈 파일 또는 지원 안 하는 확장자.
        """
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(f"image not found: {path}")
        if path.suffix.lower() not in _IMAGE_MIME_BY_EXT:
            raise ValueError(f"unsupported image extension: {path.suffix}")
        if path.stat().st_size == 0:
            raise ValueError(f"empty image: {path}")

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }
        mime = _guess_image_mime(path)

        try:
            with path.open("rb") as f:
                resp = httpx.post(
                    UPLOAD_PHOTO_URL,
                    headers=headers,
                    files={"image": (path.name, f, mime)},
                    timeout=_UPLOAD_TIMEOUT_SEC,
                )
        except httpx.TimeoutException as e:
            raise BlogApiError(
                "upload timeout", status_code=0, retryable=True
            ) from e
        except httpx.RequestError as e:
            raise BlogApiError(
                f"upload network: {type(e).__name__}",
                status_code=0,
                retryable=True,
            ) from e

        if resp.status_code == 401:
            raise BlogApiError(
                "upload unauthorized", status_code=401, retryable=False
            )
        if resp.status_code == 403:
            raise BlogApiError(
                "upload forbidden — 글쓰기 API 권한 없음 가능",
                status_code=403,
                retryable=False,
            )
        if resp.status_code == 429:
            raise BlogApiError(
                "upload rate limited", status_code=429, retryable=True
            )
        if resp.status_code >= 500:
            raise BlogApiError(
                f"upload server error HTTP {resp.status_code}",
                status_code=resp.status_code,
                retryable=True,
            )
        if resp.status_code != 200:
            raise BlogApiError(
                f"upload HTTP {resp.status_code}: {_truncate(resp.text)}",
                status_code=resp.status_code,
                retryable=False,
            )

        try:
            body = resp.json()
        except ValueError as e:
            raise BlogApiError(
                "upload: non-JSON response", status_code=200, retryable=False
            ) from e

        # 응답 구조 — 두 가지 형태 처리:
        #   {"result": {"url": "..."}}            (단수)
        #   {"result": [{"url": "..."}, ...]}     (복수)
        result = body.get("result")
        if isinstance(result, list):
            if not result or not isinstance(result[0], dict):
                raise BlogApiError(
                    "upload: empty result array", status_code=200, retryable=False
                )
            url = result[0].get("url")
        elif isinstance(result, dict):
            url = result.get("url")
        else:
            url = None

        if not url:
            raise BlogApiError(
                f"upload: no url in response — body={_truncate(str(body))}",
                status_code=200,
                retryable=False,
            )
        return str(url)


def _truncate(s: str, limit: int = 200) -> str:
    """예외 메시지용 응답 본문 잘라내기 — secret leak 방지 + 가독성."""
    if len(s) <= limit:
        return s
    return s[:limit] + "…"
