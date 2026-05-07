"""산출물 저장 — 디스크 파일 + DB 메타 (sha256/size/mime).

저장 경로: ``{artifacts_dir}/{YYYY}/{MM}/{pipeline_id}/{kind}/{sha256}{ext}``
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from blogitem.pipeline.stages import Stage


class ArtifactStore:
    """파이프라인 산출물 저장소.

    책임:
        · 파일 디스크 저장 (atomic write — temp + rename)
        · sha256/size/mime 계산
        · DB Artifact row 생성

    P2 — 본격 구현. 현재는 인터페이스만.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def save_bytes(
        self,
        pipeline_id: int,
        stage: Stage,
        kind: str,
        data: bytes,
        ext: str,
        mime: str | None = None,
    ) -> Path:
        """바이트 데이터를 파일로 저장하고 절대 경로 반환.

        Returns:
            저장된 파일의 절대 경로.
        """
        raise NotImplementedError("P2 — 구현 필요")

    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        """바이트 sha256 hex digest."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def sha256_file(path: Path) -> str:
        """파일 sha256 hex digest (스트리밍)."""
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
