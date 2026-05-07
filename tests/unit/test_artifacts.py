"""ArtifactStore — 디스크 저장 + sha256 + 경로 규약."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

import pytest

from blogitem.pipeline.artifacts import ArtifactStore
from blogitem.pipeline.stages import Stage


@pytest.fixture
def store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 5, 7, 12, 30)


class TestSaveBytes:
    def test_returns_record_with_sha_size_mime(
        self, store: ArtifactStore, fixed_now: datetime
    ) -> None:
        data = b"hello world"
        rec = store.save_bytes(
            pipeline_id=42,
            stage=Stage.DRAFT,
            kind="text",
            data=data,
            ext=".txt",
            mime="text/plain",
            now=fixed_now,
        )

        assert rec.sha256 == hashlib.sha256(data).hexdigest()
        assert rec.size == len(data)
        assert rec.mime == "text/plain"

    def test_path_format_yyyy_mm_pid_kind(
        self, store: ArtifactStore, fixed_now: datetime
    ) -> None:
        rec = store.save_bytes(
            pipeline_id=7,
            stage=Stage.DRAFT,
            kind="text",
            data=b"x",
            ext=".txt",
            now=fixed_now,
        )
        # 2026/05/7/text/{sha[:16]}.txt — 항상 forward slash
        parts = rec.rel_path.split("/")
        assert parts[0] == "2026"
        assert parts[1] == "05"
        assert parts[2] == "7"
        assert parts[3] == "text"
        assert parts[4].endswith(".txt")

    def test_file_actually_written(
        self, store: ArtifactStore, fixed_now: datetime
    ) -> None:
        data = b"hello"
        rec = store.save_bytes(
            pipeline_id=1,
            stage=Stage.DRAFT,
            kind="text",
            data=data,
            ext=".txt",
            now=fixed_now,
        )
        abs_path = store.absolute_path(rec.rel_path)
        assert abs_path.is_file()
        assert abs_path.read_bytes() == data

    def test_empty_data_rejected(self, store: ArtifactStore) -> None:
        with pytest.raises(ValueError, match="empty"):
            store.save_bytes(
                pipeline_id=1,
                stage=Stage.DRAFT,
                kind="text",
                data=b"",
                ext=".txt",
            )

    def test_ext_must_start_with_dot(self, store: ArtifactStore) -> None:
        with pytest.raises(ValueError, match="ext"):
            store.save_bytes(
                pipeline_id=1,
                stage=Stage.DRAFT,
                kind="text",
                data=b"x",
                ext="txt",
            )

    def test_no_tmp_left_on_success(
        self, store: ArtifactStore, fixed_now: datetime
    ) -> None:
        rec = store.save_bytes(
            pipeline_id=1,
            stage=Stage.DRAFT,
            kind="text",
            data=b"x",
            ext=".txt",
            now=fixed_now,
        )
        abs_path = store.absolute_path(rec.rel_path)
        # .tmp 파일이 디렉토리에 남아 있으면 안 됨
        siblings = list(abs_path.parent.iterdir())
        assert all(not p.name.endswith(".tmp") for p in siblings)


class TestSaveText:
    def test_utf8_korean(self, store: ArtifactStore, fixed_now: datetime) -> None:
        rec = store.save_text(
            pipeline_id=1,
            stage=Stage.DRAFT,
            text="안녕 세계",
            now=fixed_now,
        )
        assert rec.mime == "text/plain; charset=utf-8"
        abs_path = store.absolute_path(rec.rel_path)
        assert abs_path.read_text(encoding="utf-8") == "안녕 세계"


class TestSaveImage:
    def test_png_mime(self, store: ArtifactStore, tmp_path: Path) -> None:
        src = tmp_path / "src.png"
        # 최소 PNG 헤더 (실제 디코딩은 안 하지만 magic bytes)
        src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)

        rec = store.save_image(
            pipeline_id=1,
            stage=Stage.IMAGE,
            source_path=src,
        )
        assert rec.mime == "image/png"
        assert rec.rel_path.endswith(".png")

    def test_unsupported_extension_rejected(
        self, store: ArtifactStore, tmp_path: Path
    ) -> None:
        src = tmp_path / "src.exe"
        src.write_bytes(b"x")
        with pytest.raises(ValueError, match="unsupported"):
            store.save_image(pipeline_id=1, stage=Stage.IMAGE, source_path=src)

    def test_missing_source_file_raises(self, store: ArtifactStore) -> None:
        with pytest.raises(FileNotFoundError):
            store.save_image(
                pipeline_id=1,
                stage=Stage.IMAGE,
                source_path=Path("nonexistent.png"),
            )


class TestSha256Helpers:
    def test_sha256_bytes(self) -> None:
        assert ArtifactStore.sha256_bytes(b"hello") == hashlib.sha256(b"hello").hexdigest()

    def test_sha256_file(self, tmp_path: Path) -> None:
        p = tmp_path / "f.bin"
        p.write_bytes(b"hello")
        assert ArtifactStore.sha256_file(p) == hashlib.sha256(b"hello").hexdigest()
