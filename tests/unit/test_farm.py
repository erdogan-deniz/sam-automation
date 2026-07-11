"""Тесты scripts/achievements/farm.py.

Скрипт импортируется напрямую по пути (он не пакет). Проверяем разбор
аргументов, применение сброса/повтора прогресса (флаги --reset/--retry-errors),
маршрутизацию исходов одной игры и честный финальный отчёт.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from app.exceptions import SAMTooManyErrors
from app.safety import ErrorTracker
from app.unlock_result import UnlockResult

_FARM_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "achievements" / "farm.py"
)


def _load_farm() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "farm_ach_under_test", _FARM_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


farm = _load_farm()


# ── разбор аргументов ───────────────────────────────────────────────────────


def test_parser_defaults_all_false() -> None:
    args = farm._build_parser().parse_args([])
    assert not args.retry_errors
    assert not args.reset
    assert not args.retry_without
    assert not args.retry_done


def test_parser_retry_errors() -> None:
    assert farm._build_parser().parse_args(["--retry-errors"]).retry_errors


def test_parser_reset() -> None:
    assert farm._build_parser().parse_args(["--reset"]).reset


def test_parser_retry_without() -> None:
    assert farm._build_parser().parse_args(["--retry-without"]).retry_without


def test_parser_retry_done() -> None:
    assert farm._build_parser().parse_args(["--retry-done"]).retry_done


# ── _select_retry_subset: срез заранее обработанных игр для retry-флагов ──────


def _args(*flags: str) -> object:
    return farm._build_parser().parse_args(list(flags))


def test_select_retry_subset_without_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # --retry-without: without ∪ store_zero ∪ store_empty; done НЕ включается,
    # порядок game_ids сохранён, игры вне множества отброшены.
    monkeypatch.setattr(farm, "load_no_achievements_ids", lambda: {10})
    monkeypatch.setattr(farm, "load_store_zero_ids", lambda: {30})
    monkeypatch.setattr(farm, "load_store_empty_ids", lambda: {50})
    monkeypatch.setattr(farm, "load_done_ids", lambda: {70})
    got = farm._select_retry_subset(
        [50, 20, 30, 40, 10, 70], _args("--retry-without")
    )
    assert got == [50, 30, 10]


def test_select_retry_subset_done_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # --retry-done: только unlocked.txt; without-источники НЕ включаются.
    monkeypatch.setattr(farm, "load_done_ids", lambda: {10, 30})
    monkeypatch.setattr(farm, "load_no_achievements_ids", lambda: {50})
    monkeypatch.setattr(farm, "load_store_zero_ids", lambda: set())
    monkeypatch.setattr(farm, "load_store_empty_ids", lambda: set())
    got = farm._select_retry_subset([10, 20, 30, 50], _args("--retry-done"))
    assert got == [10, 30]


def test_select_retry_subset_both_is_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Оба флага → объединение without-среза и done.
    monkeypatch.setattr(farm, "load_no_achievements_ids", lambda: {10})
    monkeypatch.setattr(farm, "load_store_zero_ids", lambda: set())
    monkeypatch.setattr(farm, "load_store_empty_ids", lambda: set())
    monkeypatch.setattr(farm, "load_done_ids", lambda: {30})
    got = farm._select_retry_subset(
        [10, 20, 30], _args("--retry-without", "--retry-done")
    )
    assert got == [10, 30]


def test_select_retry_subset_empty_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "load_no_achievements_ids",
        "load_store_zero_ids",
        "load_store_empty_ids",
        "load_done_ids",
    ):
        monkeypatch.setattr(farm, name, lambda: set())
    got = farm._select_retry_subset(
        [1, 2, 3], _args("--retry-without", "--retry-done")
    )
    assert got == []


# ── применение сброса ───────────────────────────────────────────────────────


def test_prepare_progress_reset_clears_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(farm, "clear_progress", lambda: called.append("all"))
    monkeypatch.setattr(farm, "clear_error_ids", lambda: called.append("err"))
    farm._prepare_progress(farm._build_parser().parse_args(["--reset"]))
    assert called == ["all"]


def test_prepare_progress_retry_errors_clears_only_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(farm, "clear_progress", lambda: called.append("all"))
    monkeypatch.setattr(farm, "clear_error_ids", lambda: called.append("err"))
    farm._prepare_progress(farm._build_parser().parse_args(["--retry-errors"]))
    assert called == ["err"]


def test_prepare_progress_noop_without_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(farm, "clear_progress", lambda: called.append("all"))
    monkeypatch.setattr(farm, "clear_error_ids", lambda: called.append("err"))
    farm._prepare_progress(farm._build_parser().parse_args([]))
    assert called == []


# ── честный финальный отчёт ─────────────────────────────────────────────────
# Инвариант: прерванный (Ctrl+C) или аварийный (слишком много ошибок) прогон
# НЕ должен давать success-«✅ Готово» — только честный ⚠️ с оговоркой.


def _capture_report(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    unlocked: int,
    errors: int,
    total: int,
) -> tuple[str, str]:
    """Гоняет farm._report_result с перехватом toast/Telegram."""
    toast_msgs: list[str] = []
    tg_msgs: list[str] = []
    monkeypatch.setattr(
        farm, "toast", lambda title, msg: toast_msgs.append(f"{title}: {msg}")
    )
    monkeypatch.setattr(
        farm, "send_telegram", lambda text, cfg: tg_msgs.append(text)
    )
    farm._report_result(status, unlocked, errors, total, cfg=object())
    return toast_msgs[0], tg_msgs[0]


def test_report_clean_run_is_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toast_msg, tg_msg = _capture_report(monkeypatch, "ok", 10, 0, 10)
    assert "✅" in tg_msg
    assert "⚠️" not in tg_msg
    assert "готово" in toast_msg.lower()


def test_report_errors_downgrade_to_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toast_msg, tg_msg = _capture_report(monkeypatch, "ok", 7, 3, 10)
    assert "✅" not in tg_msg
    assert "⚠️" in tg_msg
    assert "оговорк" in toast_msg.lower()


def test_report_interrupted_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toast_msg, tg_msg = _capture_report(monkeypatch, "interrupted", 5, 0, 10)
    assert "✅" not in tg_msg
    assert "⚠️" in tg_msg
    assert "прерв" in toast_msg.lower()


def test_report_aborted_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toast_msg, tg_msg = _capture_report(monkeypatch, "aborted", 2, 5, 10)
    assert "✅" not in tg_msg
    assert "⚠️" in tg_msg
    assert "прерв" in toast_msg.lower()


# ── маршрутизация исхода одной игры (_process_one_game) ─────────────────────
# Мягкая ошибка (skip_reason="error", НЕ исключение) должна считаться ошибкой:
# иначе прогон, где все игры не загрузились, ложно рапортует ✅ (см. аудит).


class _FakeSession:
    def add_and_open_game(self, game_id: int, timeout: float) -> object:
        return object()


class _Cfg:
    load_timeout = 5
    post_commit_delay = 0.0


def _run_one(
    monkeypatch: pytest.MonkeyPatch,
    result: UnlockResult,
    tracker: ErrorTracker,
) -> tuple[bool, dict[str, list[int]]]:
    calls: dict[str, list[int]] = {
        "done": [],
        "error": [],
        "no_ach": [],
        "unmark_no_ach": [],
        "unmark_store": [],
    }
    monkeypatch.setattr(farm, "process_game", lambda *a, **k: result)
    monkeypatch.setattr(farm, "mark_done", lambda g: calls["done"].append(g))
    monkeypatch.setattr(
        farm, "mark_error_id", lambda g: calls["error"].append(g)
    )
    monkeypatch.setattr(
        farm, "mark_no_achievements", lambda g: calls["no_ach"].append(g)
    )
    monkeypatch.setattr(
        farm,
        "unmark_no_achievements",
        lambda g: calls["unmark_no_ach"].append(g),
    )
    monkeypatch.setattr(
        farm,
        "unmark_store_advisory",
        lambda g: calls["unmark_store"].append(g),
    )
    monkeypatch.setattr(farm, "close_game", lambda app: None)
    ret = farm._process_one_game(
        _FakeSession(), result.game_id, _Cfg(), tracker, []
    )
    return ret, calls


def test_process_one_game_soft_error_counts_as_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ErrorTracker(max_consecutive=100)
    result = UnlockResult(game_id=730, skipped=True, skip_reason="error")
    ret, calls = _run_one(monkeypatch, result, tracker)
    assert ret is True  # трактуется как ошибка (→ errors += 1 в main)
    assert calls["error"] == [730]
    assert calls["done"] == []
    assert tracker.total_errors == 1  # record_error, НЕ record_success


def test_process_one_game_soft_errors_trigger_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ErrorTracker(max_consecutive=1)
    result = UnlockResult(game_id=730, skipped=True, skip_reason="error")
    with pytest.raises(SAMTooManyErrors):
        _run_one(monkeypatch, result, tracker)


def test_process_one_game_unlock_marks_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ErrorTracker(max_consecutive=100)
    result = UnlockResult(game_id=570, skipped=False, total=5, newly_unlocked=5)
    ret, calls = _run_one(monkeypatch, result, tracker)
    assert ret is False
    assert calls["done"] == [570]
    assert calls["error"] == []
    assert tracker.total_errors == 0


def test_process_one_game_unlock_clears_stale_no_ach_marks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Игра оказалась с достижениями → устаревшие «нет достижений» должны уйти
    # из without И из Store-советов (иначе --retry-without гоняет её впустую).
    tracker = ErrorTracker(max_consecutive=100)
    result = UnlockResult(game_id=570, skipped=False, total=5, newly_unlocked=5)
    _ret, calls = _run_one(monkeypatch, result, tracker)
    assert calls["unmark_no_ach"] == [570]
    assert calls["unmark_store"] == [570]


def test_process_one_game_no_achievements_not_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ErrorTracker(max_consecutive=100)
    result = UnlockResult(
        game_id=999, skipped=True, skip_reason="no achievements"
    )
    ret, calls = _run_one(monkeypatch, result, tracker)
    assert ret is False
    assert calls["no_ach"] == [999]
    assert calls["error"] == []
    assert tracker.total_errors == 0


def test_process_one_game_no_achievements_clears_store_advisory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SAM подтвердил «без достижений» → авторитет у without.txt, ненадёжный
    # Store-совет снимается; but without-пометку (unmark_no_ach) НЕ трогаем.
    tracker = ErrorTracker(max_consecutive=100)
    result = UnlockResult(
        game_id=999, skipped=True, skip_reason="no achievements"
    )
    _ret, calls = _run_one(monkeypatch, result, tracker)
    assert calls["unmark_store"] == [999]
    assert calls["unmark_no_ach"] == []
