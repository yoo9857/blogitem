"""파이프라인 상태 머신 — 전이 규칙 + 검증.

잘못된 전이는 ``InvalidTransitionError``. 모든 전이는 명시적이며 호출 측은
``assert_transition`` 으로 사전 검증해야 한다.
"""

from __future__ import annotations

from blogitem.pipeline.stages import Stage, Status


class InvalidTransitionError(ValueError):
    """허용되지 않은 단계/상태 전이."""


# 정상 진행 순서
NEXT_STAGE: dict[Stage, Stage | None] = {
    Stage.TOPIC: Stage.IMAGE,
    Stage.IMAGE: Stage.DRAFT,
    Stage.DRAFT: Stage.HUMANIZE,
    Stage.HUMANIZE: Stage.CONFIRM,
    Stage.CONFIRM: Stage.PUBLISH,
    Stage.PUBLISH: None,
}

# 단계 진입 시 초기 상태
INITIAL_STATUS: dict[Stage, Status] = {
    Stage.TOPIC: Status.PENDING,
    Stage.IMAGE: Status.AWAITING_INPUT,
    Stage.DRAFT: Status.PENDING,
    Stage.HUMANIZE: Status.AWAITING_INPUT,
    Stage.CONFIRM: Status.AWAITING_REVIEW,
    Stage.PUBLISH: Status.PENDING,
}

# Orchestrator 가 자동 트리거하는 단계
AUTOMATIC_STAGES: frozenset[Stage] = frozenset({Stage.TOPIC, Stage.DRAFT, Stage.PUBLISH})

# 허용 상태 전이
ALLOWED_STATUS_TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.PENDING: frozenset({Status.RUNNING, Status.CANCELLED}),
    Status.RUNNING: frozenset({Status.DONE, Status.FAILED, Status.CANCELLED}),
    Status.AWAITING_INPUT: frozenset({Status.DONE, Status.CANCELLED}),
    Status.AWAITING_REVIEW: frozenset({Status.DONE, Status.REJECTED, Status.CANCELLED}),
    Status.DONE: frozenset(),
    Status.REJECTED: frozenset({Status.AWAITING_INPUT}),  # HUMANIZE 재실행
    Status.FAILED: frozenset({Status.PENDING}),           # 수동 재시도
    Status.CANCELLED: frozenset(),
}


def can_transition(current: Status, target: Status) -> bool:
    """상태 전이 허용 여부."""
    return target in ALLOWED_STATUS_TRANSITIONS.get(current, frozenset())


def assert_transition(current: Status, target: Status) -> None:
    """상태 전이 검증 — 위반 시 ``InvalidTransitionError``."""
    if not can_transition(current, target):
        raise InvalidTransitionError(f"{current} → {target} 전이 불가")


def next_stage(stage: Stage) -> Stage | None:
    """다음 단계. ``PUBLISH`` 면 None."""
    return NEXT_STAGE[stage]


def is_automatic(stage: Stage) -> bool:
    """blogitem 이 자동으로 진행 가능한 단계인지."""
    return stage in AUTOMATIC_STAGES
