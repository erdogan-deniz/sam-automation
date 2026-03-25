"""Тесты для app/safety.py."""

from __future__ import annotations

import pytest

from app.exceptions import SAMTooManyErrors
from app.safety import ErrorTracker


def test_initial_state() -> None:
    tracker = ErrorTracker(max_consecutive=3)
    assert tracker.total_errors == 0


def test_record_success_no_raise() -> None:
    tracker = ErrorTracker(max_consecutive=3)
    tracker.record_success()  # не должно бросать исключений


def test_record_error_increments_total() -> None:
    tracker = ErrorTracker(max_consecutive=10)
    tracker.record_error(730, ValueError("oops"))
    tracker.record_error(730, ValueError("again"))
    assert tracker.total_errors == 2


def test_record_success_resets_consecutive() -> None:
    tracker = ErrorTracker(max_consecutive=5)
    tracker.record_error(730, ValueError("err1"))
    tracker.record_error(730, ValueError("err2"))
    tracker.record_success()
    # Следующая ошибка — снова первая подряд, не должна бросить исключение
    tracker.record_error(730, ValueError("err3"))


def test_raises_at_limit() -> None:
    tracker = ErrorTracker(max_consecutive=3)
    tracker.record_error(730, ValueError("e1"))
    tracker.record_error(730, ValueError("e2"))
    with pytest.raises(SAMTooManyErrors):
        tracker.record_error(730, ValueError("e3"))


def test_does_not_raise_below_limit() -> None:
    tracker = ErrorTracker(max_consecutive=3)
    tracker.record_error(730, ValueError("e1"))
    tracker.record_error(730, ValueError("e2"))  # 2 подряд — OK


def test_reset_after_success_allows_more_errors() -> None:
    tracker = ErrorTracker(max_consecutive=2)
    tracker.record_error(730, ValueError("e1"))
    tracker.record_success()
    # После сброса снова 2 подряд
    tracker.record_error(730, ValueError("e2"))
    with pytest.raises(SAMTooManyErrors):
        tracker.record_error(730, ValueError("e3"))


def test_total_errors_not_reset_by_success() -> None:
    tracker = ErrorTracker(max_consecutive=10)
    tracker.record_error(730, ValueError("e1"))
    tracker.record_error(730, ValueError("e2"))
    tracker.record_success()
    tracker.record_error(730, ValueError("e3"))
    assert tracker.total_errors == 3
