"""다운로드 폴더 감시 — 최근 수정된 이미지 검색 + QFileSystemWatcher 통합.

설계:
    · ``list_recent_images()`` — pure 함수 (테스트 가능). 폴더 walk + 시간/확장자 필터.
    · ``make_watch_service()`` 팩토리 — Qt QObject + QFileSystemWatcher.
      파일 추가 즉시 시그널 (폴링 아닌 OS 이벤트 기반).

지원 확장자: PNG / JPG / JPEG / WebP / GIF / BMP.
사용자 홈의 Downloads 가 기본 경로.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})


def default_watch_dir() -> Path:
    """OS 사용자 홈 ``Downloads`` 폴더. 없으면 홈 자체."""
    home = Path.home()
    candidate = home / "Downloads"
    if candidate.is_dir():
        return candidate
    return home


def resolve_watch_dir(configured: str) -> Path:
    """설정값을 절대 경로로 풀이. 빈 문자열이면 default."""
    if not configured.strip():
        return default_watch_dir()
    return Path(configured).expanduser().resolve()


def list_recent_images(
    *,
    watch_dir: Path,
    max_age_min: int = 120,
    now: datetime | None = None,
) -> list[Path]:
    """``watch_dir`` 하위 (1단계만) 최근 ``max_age_min`` 분 내 수정된 이미지 목록.

    재귀하지 않음 — Downloads 폴더 직속만 (성능 + 의도 명확).
    수정 시각 내림차순 (최신 먼저).
    """
    if not watch_dir.is_dir():
        return []
    if max_age_min < 0:
        raise ValueError("max_age_min must be non-negative")

    cutoff = (now or datetime.now()) - timedelta(minutes=max_age_min)
    cutoff_ts = cutoff.timestamp()

    candidates: list[tuple[float, Path]] = []
    try:
        entries: Iterable[Path] = watch_dir.iterdir()
    except OSError:
        return []

    for entry in entries:
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in _IMAGE_EXTENSIONS:
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff_ts:
            continue
        candidates.append((mtime, entry))

    candidates.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in candidates]


def make_watch_service(
    *,
    watch_dir: Path,
    settings_window_min: int,
    parent: object | None = None,
) -> object:
    """``WatchFolderService`` 팩토리.

    PySide6 import 함수 내부 격리 — 헤드리스 환경에서도 모듈 import 가능.
    """
    from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

    class WatchFolderService(QObject):
        """폴더 변화 즉시 시그널 + 디바운스.

        QFileSystemWatcher 가 OS 단위 이벤트 (Windows 의 ReadDirectoryChangesW 등)를
        후크하여 파일 추가/변경/삭제 시 ``directoryChanged`` 시그널 발화.
        디바운스 후 ``recent_images_changed(list[Path])`` emit.
        """

        recent_images_changed = Signal(list)
        watch_started = Signal(str)  # 감시 디렉토리 경로
        watch_failed = Signal(str)

        def __init__(self) -> None:
            super().__init__(parent)  # type: ignore[arg-type]
            self._watch_dir = watch_dir
            self._window_min = settings_window_min
            self._watcher: QFileSystemWatcher | None = None
            self._debounce = QTimer(self)
            self._debounce.setSingleShot(True)
            self._debounce.setInterval(500)
            self._debounce.timeout.connect(self._emit_current)

        def start(self) -> None:
            if not self._watch_dir.is_dir():
                self.watch_failed.emit(
                    f"감시 폴더가 존재하지 않습니다: {self._watch_dir}"
                )
                return
            self._watcher = QFileSystemWatcher(self)
            self._watcher.addPath(str(self._watch_dir))
            self._watcher.directoryChanged.connect(self._on_changed)
            self.watch_started.emit(str(self._watch_dir))
            # 초기 1회
            self._emit_current()

        def stop(self) -> None:
            if self._watcher is not None:
                try:
                    paths = self._watcher.directories() + self._watcher.files()
                    if paths:
                        self._watcher.removePaths(paths)
                except Exception:  # noqa: BLE001
                    pass
                self._watcher = None
            self._debounce.stop()

        def list_now(self) -> list[Path]:
            """현재 시점 후보 목록 (즉시 호출)."""
            return list_recent_images(
                watch_dir=self._watch_dir, max_age_min=self._window_min
            )

        # ── 내부 ────────────────────────────────────────────────────────────

        def _on_changed(self, _path: str) -> None:
            # 디바운스 — 다운로드 진행 중에 directoryChanged 가 여러 번 발화하므로
            # 마지막 변화 후 0.5초 안정될 때 최종 emit.
            self._debounce.start()

        def _emit_current(self) -> None:
            self.recent_images_changed.emit(self.list_now())

    return WatchFolderService()
