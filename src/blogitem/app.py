"""QApplication 부트스트랩 + 단일 인스턴스 가드 + 메인 윈도우 시작.

부팅 절차:
    1. ``Settings`` 로드 + 로깅 초기화 (PySide6 import 전 — 빨리 로그 시작).
    2. PySide6 import + ``QLockFile`` 단일 인스턴스 가드.
    3. Alembic 마이그레이션 head 까지 실행 (DB 자동 생성/업그레이드).
    4. SQLAlchemy engine + session factory 생성.
    5. ``QApplication`` + ``MainWindow`` 시작.
    6. 종료 시 락 해제.

오류 정책:
    · 부팅 단계 실패는 ``log.exception`` + non-zero 종료 코드.
    · 시크릿 미설정은 사용자가 SettingsDialog 에서 입력하도록 — 부팅 단계 실패 X.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from blogitem import __version__


def run(argv: Sequence[str]) -> int:
    """blogitem 메인 루프.

    Args:
        argv: ``sys.argv`` 그대로.

    Returns:
        ``QApplication.exec()`` 종료 코드, 또는 단일 인스턴스 충돌 시 1.
    """
    from blogitem.config import load_settings
    from blogitem.db import make_engine, make_session_factory
    from blogitem.log import configure_logging, get_logger

    settings = load_settings()
    configure_logging(settings.log_level, settings.log_dir)
    log = get_logger(__name__)

    log.info("app.start", version=__version__, dry_run=settings.dry_run)

    # PySide6 는 부팅 후반에서만 import — 헤드리스 환경(테스트)에서도 모듈 import 자체는 가능
    from PySide6.QtCore import QLockFile, QStandardPaths
    from PySide6.QtWidgets import QApplication

    app_data_dir = Path(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    )
    app_data_dir.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(app_data_dir / "blogitem.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        log.warning("app.already_running", lock=str(app_data_dir / "blogitem.lock"))
        return 1

    try:
        _run_migrations(settings.db_path)
        engine = make_engine(settings.db_path)
        session_factory = make_session_factory(engine)

        qapp = QApplication(list(argv))
        qapp.setApplicationName("blogitem")
        qapp.setApplicationVersion(__version__)
        qapp.setOrganizationName("Signpost")

        from blogitem.ui.main_window import MainWindow

        window = MainWindow(settings=settings, session_factory=session_factory)
        window.show()

        log.info("app.window_shown")
        return qapp.exec()
    except Exception:
        log.exception("app.fatal")
        return 2
    finally:
        lock.unlock()


def _project_resources_dir() -> Path:
    """``alembic.ini`` + ``migrations/`` 루트.

    개발 모드 — 프로젝트 root.
    PyInstaller bundle — ``sys._MEIPASS``.
    """
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    # src/blogitem/app.py → src → blogitem → 프로젝트 root (3 단계 위)
    return Path(__file__).parent.parent.parent


def _run_migrations(db_path: Path) -> None:
    """Alembic 마이그레이션을 head 까지 실행."""
    import os

    from alembic import command
    from alembic.config import Config

    res = _project_resources_dir()
    cfg_path = res / "alembic.ini"
    cfg = Config(str(cfg_path))
    cfg.set_main_option("script_location", str(res / "migrations"))

    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ["BLOGITEM_DB_PATH"] = str(db_path)

    command.upgrade(cfg, "head")
