"""Тесты scripts/achievements/farm_achievements.py.

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
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "achievements"
    / "farm_achievements.py"
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
    # --retry-without: только without.txt; done НЕ включается, порядок game_ids
    # сохранён, игры вне множества отброшены.
    monkeypatch.setattr(farm, "load_no_achievements_ids", lambda: {10, 30})
    monkeypatch.setattr(farm, "load_done_ids", lambda: {70})
    got = farm._select_retry_subset(
        [50, 20, 30, 40, 10, 70], _args("--retry-without")
    )
    assert got == [30, 10]


def test_select_retry_subset_done_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # --retry-done: только unlocked.txt; without НЕ включается.
    monkeypatch.setattr(farm, "load_done_ids", lambda: {10, 30})
    monkeypatch.setattr(farm, "load_no_achievements_ids", lambda: {50})
    got = farm._select_retry_subset([10, 20, 30, 50], _args("--retry-done"))
    assert got == [10, 30]


def test_select_retry_subset_both_is_union(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Оба флага → объединение without и done.
    monkeypatch.setattr(farm, "load_no_achievements_ids", lambda: {10})
    monkeypatch.setattr(farm, "load_done_ids", lambda: {30})
    got = farm._select_retry_subset(
        [10, 20, 30], _args("--retry-without", "--retry-done")
    )
    assert got == [10, 30]


def test_select_retry_subset_empty_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("load_no_achievements_ids", "load_done_ids"):
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
    # Игра оказалась с достижениями → устаревшая пометка «нет достижений» должна
    # уйти из without.txt (иначе --retry-without гоняет её впустую).
    tracker = ErrorTracker(max_consecutive=100)
    result = UnlockResult(game_id=570, skipped=False, total=5, newly_unlocked=5)
    _ret, calls = _run_one(monkeypatch, result, tracker)
    assert calls["unmark_no_ach"] == [570]


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
    # SAM «нет достижений» не трогает without-пометку (она как раз и ставится).
    assert calls["unmark_no_ach"] == []


# ── персист переживает SAMTooManyErrors из record_error (F1, аудит 2026-08-10) ─
# tracker.record_error бросает SAMTooManyErrors на N-й подряд ошибке. Раньше
# он вызывался ПЕРВЫМ в каждой error-ветке — бросок пропускал mark_error_id/
# results.append того же блока, и игра, добившая лимит, не попадала ни в
# error.txt, ни в results (молча ретраится следующим прогоном без следа).


def test_soft_error_abort_still_marks_error_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ErrorTracker(max_consecutive=1)
    result = UnlockResult(game_id=730, skipped=True, skip_reason="error")
    calls: dict[str, list[int]] = {"error": []}
    monkeypatch.setattr(farm, "process_game", lambda *a, **k: result)
    monkeypatch.setattr(
        farm, "mark_error_id", lambda g: calls["error"].append(g)
    )
    monkeypatch.setattr(farm, "close_game", lambda app: None)

    with pytest.raises(SAMTooManyErrors):
        farm._process_one_game(_FakeSession(), 730, _Cfg(), tracker, [])

    assert calls["error"] == [730]


def test_samerror_abort_still_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.exceptions import SAMError

    tracker = ErrorTracker(max_consecutive=1)
    calls: dict[str, list[int]] = {"error": []}
    monkeypatch.setattr(
        farm,
        "process_game",
        lambda *a, **k: (_ for _ in ()).throw(SAMError("boom")),
    )
    monkeypatch.setattr(
        farm, "mark_error_id", lambda g: calls["error"].append(g)
    )
    monkeypatch.setattr(farm, "close_game", lambda app: None)
    results: list[UnlockResult] = []

    with pytest.raises(SAMTooManyErrors):
        farm._process_one_game(_FakeSession(), 730, _Cfg(), tracker, results)

    assert calls["error"] == [730]
    assert results and results[0].game_id == 730


def test_generic_exception_abort_still_persists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker = ErrorTracker(max_consecutive=1)
    calls: dict[str, list[int]] = {"error": []}
    monkeypatch.setattr(
        farm,
        "process_game",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        farm, "mark_error_id", lambda g: calls["error"].append(g)
    )
    monkeypatch.setattr(farm, "close_game", lambda app: None)
    results: list[UnlockResult] = []

    with pytest.raises(SAMTooManyErrors):
        farm._process_one_game(_FakeSession(), 730, _Cfg(), tracker, results)

    assert calls["error"] == [730]
    assert results and results[0].game_id == 730


# ── _teardown_picker переживает сбой kill_process (F3, аудит 2026-08-10) ──────
# kill_process(proc) в finally main() не имел собственной защиты (в отличие
# от close_game в _process_one_game) — сбой (напр. PermissionError в гонке
# терминации уже выходящего процесса) пропустил бы честный
# _log_summary/_report_result, идущие следом.


def test_teardown_picker_survives_kill_process_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(proc):
        raise PermissionError("процесс уже завершается")

    monkeypatch.setattr(farm, "kill_process", _boom)

    farm._teardown_picker(object())  # не должно бросить


# ── _teardown_picker подчищает осиротевшие SAM.Game.exe (HIGH #3, аудит
# 2026-08-10) ────────────────────────────────────────────────────────────────
# finally main() убивал только Picker (kill_process(proc)) без бэкстопа
# kill_all_sam_games(), в отличие от boost_playtime.py/cards/farm_cards.py — сирота
# SAM.Game.exe (напр. из бага picker_session.py Step-2, или Ctrl+C во время
# обработки игры) никогда не подчищался, конфликт с run-lock инвариантом.


def test_teardown_picker_sweeps_orphaned_sam_games(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(farm, "kill_process", lambda proc: calls.append("proc"))
    monkeypatch.setattr(
        farm, "kill_all_sam_games", lambda: calls.append("sweep")
    )

    farm._teardown_picker(object())

    assert calls == ["proc", "sweep"]


def test_teardown_picker_sweeps_even_if_kill_process_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(proc):
        raise PermissionError("процесс уже завершается")

    calls: list[str] = []
    monkeypatch.setattr(farm, "kill_process", _boom)
    monkeypatch.setattr(
        farm, "kill_all_sam_games", lambda: calls.append("sweep")
    )

    farm._teardown_picker(object())  # не должно бросить

    assert calls == ["sweep"]  # бэкстоп не пропущен из-за сбоя kill_process


def test_teardown_picker_survives_sweep_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(farm, "kill_process", lambda proc: None)

    def _boom_sweep():
        raise OSError("CreateToolhelp32Snapshot упал")

    monkeypatch.setattr(farm, "kill_all_sam_games", _boom_sweep)

    farm._teardown_picker(object())  # не должно бросить


# ── поломка SAM.Picker: перезапуск вместо ложных error ──────────────────────
# Живой прогон 21.10.2026: после диалога на appid 5 Picker перестал принимать
# ввод, 99 следующих игр упали за минуту и легли в error.txt, разблокировано 0.


class _Ok:
    def add_and_open_game(self, game_id: int, timeout: float) -> object:
        return object()


class _Broken:
    def __init__(self, bad: set[int] | None = None) -> None:
        self.bad = bad  # None — ломается на любой игре

    def add_and_open_game(self, game_id: int, timeout: float) -> object:
        if self.bad is None or game_id in self.bad:
            raise farm.SAMPickerBroken("окно SAM.Picker не принимает ввод")
        return object()


class _RecCfg(_Cfg):
    sam_game_exe_path = "x"
    launch_delay = 0


def _recovery_env(monkeypatch: pytest.MonkeyPatch, sessions: list) -> dict:
    """Подменяет SAM вокруг _process_with_recovery; sessions — по запускам."""
    calls: dict = {"done": [], "error": [], "launch": 0, "teardown": []}
    queue = list(sessions)

    def _launch(path, launch_delay=0):  # type: ignore[no-untyped-def]
        calls["launch"] += 1
        return f"proc{calls['launch']}", queue.pop(0)

    monkeypatch.setattr(farm, "launch_picker", _launch)
    monkeypatch.setattr(farm, "_teardown_picker", calls["teardown"].append)
    monkeypatch.setattr(
        farm,
        "process_game",
        lambda app, gid, **k: UnlockResult(game_id=gid, total=3),
    )
    monkeypatch.setattr(farm, "mark_done", calls["done"].append)
    monkeypatch.setattr(farm, "mark_error_id", calls["error"].append)
    monkeypatch.setattr(farm, "unmark_no_achievements", lambda g: None)
    monkeypatch.setattr(farm, "close_game", lambda app: None)
    return calls


def _run_games(picker, games: list[int], tracker=None) -> list:  # type: ignore[no-untyped-def]
    results: list = []
    tracker = tracker or ErrorTracker(max_consecutive=100)
    for gid in games:
        farm._process_with_recovery(picker, gid, _RecCfg(), tracker, results)
    return results


def test_broken_picker_is_restarted_and_game_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _recovery_env(monkeypatch, [_Ok()])
    picker = farm._Picker("proc0", _Broken())

    _run_games(picker, [7])

    assert calls["error"] == []  # игра не виновата — не в error.txt
    assert calls["done"] == [7]
    assert calls["teardown"] == ["proc0"]
    assert calls["launch"] == 1
    assert picker.proc == "proc1"
    assert picker.breaks_in_row == 0


def test_game_breaking_picker_twice_goes_to_error_and_run_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _recovery_env(monkeypatch, [_Broken({5}), _Broken({5})])
    picker = farm._Picker("proc0", _Broken({5}))
    tracker = ErrorTracker(max_consecutive=100)

    results = _run_games(picker, [5, 7], tracker)

    assert calls["error"] == [5]
    assert calls["done"] == [7]
    assert calls["launch"] == 2
    assert tracker.total_errors == 1
    assert results[0].skip_reason  # причина не пустая


def test_picker_unrecoverable_after_three_restarts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _recovery_env(monkeypatch, [_Broken() for _ in range(5)])
    picker = farm._Picker("proc0", _Broken())

    with pytest.raises(farm._PickerUnrecoverable):
        _run_games(picker, [5, 7, 8, 9])

    assert calls["launch"] == 3
    assert calls["error"] == [5]  # только игра, сломавшая Picker дважды


def test_failed_picker_restart_is_unrecoverable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.exceptions import SAMLaunchError

    _recovery_env(monkeypatch, [])

    def _fail(path, launch_delay=0):  # type: ignore[no-untyped-def]
        raise SAMLaunchError("SAM.Picker.exe завершился с кодом 1")

    monkeypatch.setattr(farm, "launch_picker", _fail)
    picker = farm._Picker("proc0", _Broken())

    with pytest.raises(farm._PickerUnrecoverable, match="кодом 1"):
        _run_games(picker, [7])


def test_exception_with_empty_text_reports_its_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ElementNotEnabled(Exception):
        pass

    def _boom(*a, **k):  # type: ignore[no-untyped-def]
        raise ElementNotEnabled()

    monkeypatch.setattr(farm, "process_game", _boom)
    monkeypatch.setattr(farm, "mark_error_id", lambda g: None)
    monkeypatch.setattr(farm, "close_game", lambda app: None)
    results: list = []
    farm._process_one_game(
        _FakeSession(), 7, _Cfg(), ErrorTracker(max_consecutive=100), results
    )
    assert results[0].skip_reason == "ElementNotEnabled"


def test_report_picker_broken_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toast_msg, tg_msg = _capture_report(monkeypatch, "picker_broken", 2, 1, 10)
    assert "✅" not in tg_msg
    assert "SAM.Picker" in toast_msg


# ── «нет в библиотеке» от SAM: отдельный список, не ошибка ───────────────────


def test_not_owned_goes_to_own_list_not_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.exceptions import SAMGameNotOwned

    class _NotOwned:
        def add_and_open_game(self, game_id: int, timeout: float) -> object:
            raise SAMGameNotOwned(game_id, "нет в библиотеке")

    marked: dict[str, list[int]] = {"not_owned": [], "error": []}
    monkeypatch.setattr(farm, "mark_not_owned", marked["not_owned"].append)
    monkeypatch.setattr(farm, "mark_error_id", marked["error"].append)
    monkeypatch.setattr(farm, "close_game", lambda app: None)
    tracker = ErrorTracker(max_consecutive=2)
    results: list[UnlockResult] = []

    for gid in (1, 2, 3):  # больше лимита подряд — стопа нет
        assert (
            farm._process_one_game(_NotOwned(), gid, _Cfg(), tracker, results)
            is False
        )

    assert marked == {"not_owned": [1, 2, 3], "error": []}
    assert tracker.total_errors == 0
    assert results[0].skip_reason == "not owned"


def test_resume_filter_skips_not_owned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(farm, "load_done_ids", lambda: {1})
    monkeypatch.setattr(farm, "load_error_ids", lambda: {2})
    monkeypatch.setattr(farm, "load_no_achievements_ids", lambda: {3})
    monkeypatch.setattr(farm, "load_not_owned_ids", lambda: {4})
    assert farm._apply_resume_filter([1, 2, 3, 4, 5]) == [5]
