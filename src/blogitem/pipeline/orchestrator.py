"""Orchestrator — PENDING 상태 자동 단계를 주기적으로 자동 실행.

설계:
    · ``OrchestratorService`` (QObject) — QTimer + AutoStageWorker 단일 인스턴스 관리.
    · 한 번에 하나만 실행 (single-flight) — 중복 호출 방지 + 비용/한도 제어.
    · 워커 종료 후 즉시 다음 PENDING 검색 → 체이닝 (사용자 입력 없이도 줄줄이 처리).
    · 사람 게이트 단계(IMAGE/HUMANIZE/CONFIRM)는 건드리지 않음 — 자동 단계 외 감지 X.

설정:
    · ``settings.orchestrator_enabled`` — 켜야만 작동.
    · ``settings.orchestrator_interval_min`` — 백업 폴링 주기 (체이닝 외).

시그널:
    · pipeline_started(int, str)   — 워커 시작 알림 (pipeline_id, stage)
    · pipeline_advanced(int, str)  — 단계 성공
    · pipeline_failed(int, str)    — 단계 실패 (보존, 자동 재시도 X)
    · output_line(str)              — 자동 단계의 CLI 스트리밍 출력
    · idle()                        — 처리할 PENDING 없음
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from blogitem.pipeline.stages import Stage, Status

if TYPE_CHECKING:
    from blogitem.config import Settings
    from blogitem.pipeline.dto import PipelineDTO
    from blogitem.pipeline.service import PipelineService


_AUTOMATIC_PENDING_STAGES = frozenset({Stage.TOPIC, Stage.DRAFT, Stage.PUBLISH})


def find_next_automatic_pending(service: PipelineService) -> PipelineDTO | None:
    """다음에 자동 실행할 PENDING 파이프라인 1개 (id 오름차순). 없으면 None."""
    pipelines = service.list_pipelines(limit=500)
    candidates = [
        p
        for p in pipelines
        if p.status == Status.PENDING and p.current_stage in _AUTOMATIC_PENDING_STAGES
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.id)
    return candidates[0]


def make_orchestrator_service(
    *,
    service: PipelineService,
    settings: Settings,
    parent: object | None = None,
) -> object:
    """``OrchestratorService`` 팩토리.

    PySide6 import 를 헤드리스 환경에서도 모듈 import 자체는 가능하게
    함수로 격리. 실제 ``QObject`` 상속 클래스는 함수 내부 정의.
    """
    from PySide6.QtCore import QObject, QTimer, Signal

    class OrchestratorService(QObject):
        pipeline_started = Signal(int, str)
        pipeline_advanced = Signal(int, str)
        pipeline_failed = Signal(int, str)
        output_line = Signal(str)
        idle = Signal()

        def __init__(self) -> None:
            super().__init__(parent)  # type: ignore[arg-type]
            self._service = service
            self._settings = settings
            self._timer = QTimer(self)
            self._timer.timeout.connect(self.tick)
            self._current_worker: object | None = None
            self._enabled = False

        @property
        def is_running(self) -> bool:
            """단계 워커가 실제 실행 중인지."""
            w = self._current_worker
            if w is None:
                return False
            try:
                return bool(w.isRunning())  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                return False

        @property
        def enabled(self) -> bool:
            return self._enabled

        def start(self, *, interval_min: int | None = None) -> None:
            from blogitem.log import get_logger

            interval = interval_min or self._settings.orchestrator_interval_min
            if interval < 1:
                raise ValueError("interval must be >= 1 minute")

            self._enabled = True
            self._timer.start(interval * 60 * 1000)
            get_logger(__name__).info("orchestrator.start", interval_min=interval)
            self.tick()

        def stop(self) -> None:
            from blogitem.log import get_logger

            self._enabled = False
            self._timer.stop()
            if self._current_worker is not None and self.is_running:
                try:
                    self._current_worker.requestInterruption()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
            get_logger(__name__).info("orchestrator.stop")

        def tick(self) -> None:
            from blogitem.log import get_logger

            log = get_logger(__name__)

            if not self._enabled:
                return
            if self.is_running:
                log.debug("orchestrator.tick_skipped", reason="worker_running")
                return

            try:
                target = find_next_automatic_pending(self._service)
            except Exception as e:  # noqa: BLE001
                log.warning("orchestrator.tick_failed", err=f"{type(e).__name__}: {e}")
                return

            if target is None:
                log.debug("orchestrator.idle")
                self.idle.emit()
                return

            log.info(
                "orchestrator.dispatch",
                pipeline_id=target.id,
                stage=target.current_stage.value,
            )
            self._launch_worker(target)

        # ── 내부 ─────────────────────────────────────────────────────────────

        def _launch_worker(self, target: PipelineDTO) -> None:
            from blogitem.ui.workers.claude_worker import AutoStageWorker

            worker = AutoStageWorker(
                pipeline_id=target.id,
                stage=target.current_stage,
                service=self._service,
                settings=self._settings,
                parent=self,
            )
            worker.output_line.connect(self.output_line.emit)
            worker.finished_ok.connect(
                lambda pid, _path: self._on_worker_ok(pid)
            )
            worker.failed.connect(self._on_worker_fail)
            worker.finished.connect(self._on_worker_finished)

            self._current_worker = worker
            self.pipeline_started.emit(target.id, target.current_stage.value)
            worker.start()

        def _on_worker_ok(self, pipeline_id: int) -> None:
            dto = self._service.get_pipeline(pipeline_id)
            stage = dto.current_stage.value if dto else "?"
            self.pipeline_advanced.emit(pipeline_id, stage)

        def _on_worker_fail(self, pipeline_id: int, message: str) -> None:
            self.pipeline_failed.emit(pipeline_id, message)

        def _on_worker_finished(self) -> None:
            from blogitem.log import get_logger

            self._current_worker = None
            get_logger(__name__).debug("orchestrator.worker_done")
            # 체이닝 — 워커 종료 후 100ms 뒤 즉시 다음 후보 검색.
            # 짧은 지연 — Qt 이벤트 루프가 이전 시그널 정리할 시간 확보.
            QTimer.singleShot(100, self.tick)

    return OrchestratorService()


# ── 호환 별칭 (기존 stub) ─────────────────────────────────────────────────────


class Orchestrator:
    """레거시 stub — 사용 X. ``make_orchestrator_service`` 사용."""

    def tick(self) -> dict[str, int]:
        raise NotImplementedError("use make_orchestrator_service() instead")
