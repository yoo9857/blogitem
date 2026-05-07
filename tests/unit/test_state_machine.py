"""상태 머신 전이 규칙 단위 테스트."""

from __future__ import annotations

import pytest

from blogitem.pipeline.stages import Stage, Status
from blogitem.pipeline.state_machine import (
    InvalidTransitionError,
    assert_transition,
    can_transition,
    is_automatic,
    next_stage,
)


class TestStageOrder:
    def test_normal_progression(self) -> None:
        assert next_stage(Stage.TOPIC) == Stage.IMAGE
        assert next_stage(Stage.IMAGE) == Stage.DRAFT
        assert next_stage(Stage.DRAFT) == Stage.HUMANIZE
        assert next_stage(Stage.HUMANIZE) == Stage.CONFIRM
        assert next_stage(Stage.CONFIRM) == Stage.PUBLISH
        assert next_stage(Stage.PUBLISH) is None

    def test_automatic_stages(self) -> None:
        assert is_automatic(Stage.TOPIC)
        assert is_automatic(Stage.DRAFT)
        assert is_automatic(Stage.PUBLISH)
        assert not is_automatic(Stage.IMAGE)       # 사람 업로드 대기
        assert not is_automatic(Stage.HUMANIZE)    # 사람 업로드 대기
        assert not is_automatic(Stage.CONFIRM)     # 사람 컨펌


class TestStatusTransitions:
    def test_pending_can_run_or_cancel(self) -> None:
        assert can_transition(Status.PENDING, Status.RUNNING)
        assert can_transition(Status.PENDING, Status.CANCELLED)
        assert not can_transition(Status.PENDING, Status.DONE)

    def test_running_terminal_states(self) -> None:
        assert can_transition(Status.RUNNING, Status.DONE)
        assert can_transition(Status.RUNNING, Status.FAILED)
        assert can_transition(Status.RUNNING, Status.CANCELLED)
        assert not can_transition(Status.RUNNING, Status.PENDING)

    def test_rejected_loops_back_to_input(self) -> None:
        # CONFIRM 거절 → HUMANIZE 재업로드 대기
        assert can_transition(Status.REJECTED, Status.AWAITING_INPUT)

    def test_failed_can_be_retried(self) -> None:
        # 데드레터 → 수동 재큐잉
        assert can_transition(Status.FAILED, Status.PENDING)

    def test_done_is_terminal(self) -> None:
        for target in Status:
            assert not can_transition(Status.DONE, target)

    def test_cancelled_is_terminal(self) -> None:
        for target in Status:
            assert not can_transition(Status.CANCELLED, target)

    def test_assert_transition_raises_on_invalid(self) -> None:
        with pytest.raises(InvalidTransitionError):
            assert_transition(Status.DONE, Status.RUNNING)
