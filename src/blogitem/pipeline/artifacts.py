"""산출물 저장 — 디스크 파일 (atomic write) + sha256/size/mime 메타.

저장 경로:
    ``{root}/{YYYY}/{MM}/{pipeline_id}/{kind}/{sha[:16]}{ext}``

저장 후 DB row 생성은 호출 측 (PipelineService) 책임 — 트랜잭션 묶음 제어.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from blogitem.pipeline.dto import ArtifactRecord

if TYPE_CHECKING:
    from blogitem.pipeline.stages import Stage


_IMAGE_MIME_BY_EXT: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


class ArtifactStore:
    """파일시스템 산출물 저장소.

    경로/sha 계산만 담당. DB I/O 는 호출 측이 ORM 으로 처리.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # ── 저장 ────────────────────────────────────────────────────────────────

    def save_bytes(
        self,
        *,
        pipeline_id: int,
        stage: Stage,
        kind: str,
        data: bytes,
        ext: str,
        mime: str | None = None,
        now: datetime | None = None,
    ) -> ArtifactRecord:
        """바이트 데이터 → 디스크 + 메타.

        Args:
            pipeline_id: 소속 파이프라인.
            stage: 산출 단계.
            kind: ``text`` | ``image`` | ``json``.
            data: 바이트.
            ext: ``.png`` ``.txt`` 등 확장자 (점 포함).
            mime: 명시적 MIME. 없으면 None.
            now: 시각 — 테스트 주입용.
        """
        if not data:
            raise ValueError("empty data not allowed")
        if not ext.startswith("."):
            raise ValueError(f"ext must start with '.': {ext!r}")

        sha = hashlib.sha256(data).hexdigest()
        when = now or datetime.now()
        rel = (
            Path(f"{when.year:04d}")
            / f"{when.month:02d}"
            / str(pipeline_id)
            / kind
            / f"{sha[:16]}{ext}"
        )
        abs_path = self._root / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        # atomic write — 같은 디렉토리에 .tmp 후 rename
        tmp = abs_path.with_name(abs_path.name + ".tmp")
        try:
            tmp.write_bytes(data)
            os.replace(tmp, abs_path)  # POSIX rename — atomic on same FS
        except Exception:
            tmp.unlink(missing_ok=True)
            raise

        return ArtifactRecord(
            rel_path=str(rel).replace("\\", "/"),
            sha256=sha,
            size=len(data),
            mime=mime,
        )

    def save_text(
        self,
        *,
        pipeline_id: int,
        stage: Stage,
        text: str,
        ext: str = ".txt",
        now: datetime | None = None,
    ) -> ArtifactRecord:
        """UTF-8 텍스트 저장."""
        return self.save_bytes(
            pipeline_id=pipeline_id,
            stage=stage,
            kind="text",
            data=text.encode("utf-8"),
            ext=ext,
            mime="text/plain; charset=utf-8",
            now=now,
        )

    def save_image(
        self,
        *,
        pipeline_id: int,
        stage: Stage,
        source_path: Path,
        now: datetime | None = None,
    ) -> ArtifactRecord:
        """파일 → 이미지 산출물 저장. 확장자 기반 MIME 추정."""
        source_path = Path(source_path)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        data = source_path.read_bytes()
        if not data:
            raise ValueError(f"empty image: {source_path}")
        ext = source_path.suffix.lower()
        if ext not in _IMAGE_MIME_BY_EXT:
            raise ValueError(f"unsupported image ext: {ext}")
        return self.save_bytes(
            pipeline_id=pipeline_id,
            stage=stage,
            kind="image",
            data=data,
            ext=ext,
            mime=_IMAGE_MIME_BY_EXT[ext],
            now=now,
        )

    # ── 조회 ────────────────────────────────────────────────────────────────

    def absolute_path(self, rel_path: str) -> Path:
        """저장된 산출물의 절대 경로."""
        return self._root / rel_path

    # ── sha 헬퍼 ────────────────────────────────────────────────────────────

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def sha256_file(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
