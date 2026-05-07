"""스모크 — 모든 주요 모듈이 import 에러 없이 로드되는지."""

from __future__ import annotations


def test_package_version() -> None:
    import blogitem

    assert blogitem.__version__


def test_core_modules_import() -> None:
    import blogitem.app  # noqa: F401
    import blogitem.config  # noqa: F401
    import blogitem.db  # noqa: F401
    import blogitem.log  # noqa: F401
    import blogitem.secrets  # noqa: F401


def test_pipeline_modules_import() -> None:
    import blogitem.pipeline.artifacts  # noqa: F401
    import blogitem.pipeline.models  # noqa: F401
    import blogitem.pipeline.orchestrator  # noqa: F401
    import blogitem.pipeline.stages  # noqa: F401
    import blogitem.pipeline.state_machine  # noqa: F401


def test_ai_modules_import() -> None:
    import blogitem.ai.base  # noqa: F401
    import blogitem.ai.claude  # noqa: F401
    import blogitem.ai.prompts  # noqa: F401


def test_channels_modules_import() -> None:
    import blogitem.channels.base  # noqa: F401
    import blogitem.channels.email_to_blog  # noqa: F401
    import blogitem.channels.naver  # noqa: F401


def test_naver_modules_import() -> None:
    import blogitem.naver.blog_api  # noqa: F401
    import blogitem.naver.oauth  # noqa: F401
    import blogitem.naver.token_store  # noqa: F401


def test_queue_modules_import() -> None:
    import blogitem.queue.store  # noqa: F401
    import blogitem.queue.worker  # noqa: F401


def test_watchdog_and_notify_import() -> None:
    import blogitem.notify.notifier  # noqa: F401
    import blogitem.watchdog.monitor  # noqa: F401


def test_ui_modules_import() -> None:
    """UI 모듈 import — QApplication 없이 클래스 정의 로드만 확인."""
    import blogitem.ui.confirm_dialog  # noqa: F401
    import blogitem.ui.diff_view  # noqa: F401
    import blogitem.ui.main_window  # noqa: F401
    import blogitem.ui.pipeline_detail  # noqa: F401
    import blogitem.ui.pipeline_list  # noqa: F401
    import blogitem.ui.settings_dialog  # noqa: F401
    import blogitem.ui.stage_view  # noqa: F401
    import blogitem.ui.upload_dialog  # noqa: F401
    import blogitem.ui.workers.claude_worker  # noqa: F401
    import blogitem.ui.workers.publish_worker  # noqa: F401
