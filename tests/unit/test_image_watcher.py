"""WatchFolderMonitor — list_recent_images 단위 테스트."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from blogitem.image.watcher import (
    default_watch_dir,
    list_recent_images,
    resolve_watch_dir,
)


def _touch(path: Path, *, mtime_ago_min: float = 0.0) -> Path:
    """파일 생성 + mtime 강제."""
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    when = datetime.now() - timedelta(minutes=mtime_ago_min)
    ts = when.timestamp()
    import os

    os.utime(path, (ts, ts))
    return path


class TestListRecentImages:
    def test_empty_dir_returns_empty(self, tmp_path: Path) -> None:
        assert list_recent_images(watch_dir=tmp_path, max_age_min=120) == []

    def test_finds_recent_png(self, tmp_path: Path) -> None:
        _touch(tmp_path / "a.png", mtime_ago_min=10)
        result = list_recent_images(watch_dir=tmp_path, max_age_min=120)
        assert len(result) == 1
        assert result[0].name == "a.png"

    def test_skips_old_files(self, tmp_path: Path) -> None:
        _touch(tmp_path / "old.png", mtime_ago_min=200)
        assert list_recent_images(watch_dir=tmp_path, max_age_min=120) == []

    def test_filters_by_extension(self, tmp_path: Path) -> None:
        _touch(tmp_path / "doc.txt", mtime_ago_min=5)
        _touch(tmp_path / "code.py", mtime_ago_min=5)
        _touch(tmp_path / "img.png", mtime_ago_min=5)
        _touch(tmp_path / "img.jpg", mtime_ago_min=5)
        _touch(tmp_path / "img.webp", mtime_ago_min=5)

        result = list_recent_images(watch_dir=tmp_path, max_age_min=120)
        names = sorted(p.name for p in result)
        assert names == ["img.jpg", "img.png", "img.webp"]

    def test_sorted_by_mtime_descending(self, tmp_path: Path) -> None:
        # 더 오래된 파일이 더 옛 mtime
        _touch(tmp_path / "old.png", mtime_ago_min=60)
        _touch(tmp_path / "newer.png", mtime_ago_min=30)
        _touch(tmp_path / "newest.png", mtime_ago_min=5)

        result = list_recent_images(watch_dir=tmp_path, max_age_min=120)
        assert [p.name for p in result] == ["newest.png", "newer.png", "old.png"]

    def test_does_not_recurse(self, tmp_path: Path) -> None:
        # 하위 디렉토리의 이미지는 무시 (성능 + 의도 명확)
        sub = tmp_path / "sub"
        sub.mkdir()
        _touch(sub / "deep.png", mtime_ago_min=5)
        _touch(tmp_path / "top.png", mtime_ago_min=5)

        result = list_recent_images(watch_dir=tmp_path, max_age_min=120)
        assert [p.name for p in result] == ["top.png"]

    def test_negative_max_age_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            list_recent_images(watch_dir=tmp_path, max_age_min=-1)

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "no-such"
        assert list_recent_images(watch_dir=nonexistent, max_age_min=120) == []

    def test_case_insensitive_extension(self, tmp_path: Path) -> None:
        _touch(tmp_path / "UPPER.PNG", mtime_ago_min=5)
        _touch(tmp_path / "Mixed.JpG", mtime_ago_min=5)

        result = list_recent_images(watch_dir=tmp_path, max_age_min=120)
        assert len(result) == 2


class TestResolveWatchDir:
    def test_empty_uses_default(self) -> None:
        # default_watch_dir 는 환경에 따라 ~/Downloads 또는 ~ 반환
        result = resolve_watch_dir("")
        assert result == default_watch_dir()

    def test_explicit_path(self, tmp_path: Path) -> None:
        result = resolve_watch_dir(str(tmp_path))
        assert result == tmp_path.resolve()

    def test_whitespace_treated_as_empty(self) -> None:
        assert resolve_watch_dir("   ") == default_watch_dir()


class TestImagePrompts:
    """ai/prompts.py 의 image_prompts() 검증."""

    def test_returns_system_and_user(self) -> None:
        from blogitem.ai.prompts import PromptLibrary

        sys_p, usr_p = PromptLibrary().image_prompts(
            lecture_meta={"title": "변수와 자료형", "summary": "..."},
            series_topic="C언어 20강",
            body_image_count=3,
        )
        assert "JSON" in sys_p
        assert "C언어 20강" in usr_p
        assert "변수와 자료형" in usr_p
        assert "thumbnail" in usr_p

    def test_body_image_count_in_user(self) -> None:
        from blogitem.ai.prompts import PromptLibrary

        _, usr_p = PromptLibrary().image_prompts(
            lecture_meta={"title": "x"},
            body_image_count=2,
        )
        # 2 body + 1 thumbnail = 3
        assert "3개" in usr_p or "정확히 3" in usr_p

    def test_clamps_count(self) -> None:
        from blogitem.ai.prompts import PromptLibrary

        # body_image_count=10 → max 5 로 클램프
        _, usr_p = PromptLibrary().image_prompts(
            lecture_meta={"title": "x"},
            body_image_count=10,
        )
        assert "정확히 6" in usr_p or "6개" in usr_p  # 5 body + 1 thumbnail

    def test_no_series_topic_omits_line(self) -> None:
        from blogitem.ai.prompts import PromptLibrary

        _, usr_p = PromptLibrary().image_prompts(
            lecture_meta={"title": "x"},
            series_topic=None,
        )
        assert "시리즈 주제" not in usr_p
