"""Тесты _boost_loop: классификация survivors/failed, Ctrl+C, мульти-батч."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_BOOST_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "playtime" / "boost.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "boost_under_test", _BOOST_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


boost = _load()


def _cfg(**over: object) -> SimpleNamespace:
    base = {
        "playtime_concurrent_games": 10,
        "playtime_idle_duration": 1,
        "launch_stagger": 0.0,
        "sam_game_exe_path": "x",
    }
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _no_real_side_effects(monkeypatch):  # type: ignore[no-untyped-def]
    # _boost_loop на выходе зовёт win32 kill_all_sam_games и уведомления
    # (toast/send_telegram) — по умолчанию no-op, чтобы тесты не убивали живой
    # SAM и не слали сеть. Тесты, проверяющие их, переопределяют своим mock.
    monkeypatch.setattr(boost, "kill_all_sam_games", lambda: None)
    monkeypatch.setattr(boost, "send_telegram", lambda *a, **k: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    # finally-свип зовёт kill_process на фейковых процессах — no-op по умолчанию;
    # тесты, считающие убийства, переопределяют своим mock.
    monkeypatch.setattr(boost, "kill_process", lambda p: None)


def test_boost_loop_marks_done_skip_and_spares_known(monkeypatch):
    done: list[int] = []
    skip: list[int] = []
    seen: dict[str, object] = {}
    monkeypatch.setattr(boost, "mark_playtime_done", done.append)
    monkeypatch.setattr(boost, "mark_playtime_skip", skip.append)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )

    # Стаб как реальная функция: 10/20 выжили, 30 провалился (через on_failed).
    def fake_idle(active, idle, on_failed=None):
        seen["idle"] = idle
        if on_failed is not None:
            on_failed(30)
        return ([10, 20], [30])

    monkeypatch.setattr(boost, "idle_and_split_survivors", fake_idle)

    games = [
        {"appid": 10, "name": "A", "playtime_forever": 0, "known": True},
        {"appid": 20, "name": "B", "playtime_forever": 0, "known": False},
        {"appid": 30, "name": "C", "playtime_forever": 0, "known": False},
    ]
    boost._boost_loop(games, _cfg(playtime_idle_duration=7))

    # unknown-выживший → done; known-выживший НЕ пишем; провал → skip (on_failed)
    assert done == [20]
    assert skip == [30]
    # idle_duration проброшен в функцию
    assert seen["idle"] == 7


def test_boost_loop_blind_run_does_not_persist_done(monkeypatch):
    # RA-A: persist_done=False (слепой прогон, пустой owned-games) → выжившие
    # НЕ пишутся в done.txt. Транзиентно-пустой GetOwnedGames больше не травит
    # всю библиотеку (инвариант «unverified → НЕ done»).
    done: list[int] = []
    monkeypatch.setattr(boost, "mark_playtime_done", done.append)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )
    monkeypatch.setattr(
        boost,
        "idle_and_split_survivors",
        lambda active, idle, on_failed=None: (list(active.keys()), []),
    )

    games = [{"appid": 10, "name": "A", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg(), persist_done=False)

    assert done == []  # слепой прогон ничего не хоронит в done


def test_boost_loop_persist_done_true_marks_unknown(monkeypatch):
    # Контроль: не-слепой прогон (persist_done=True, дефолт) — unknown-выживший
    # ПИШЕТСЯ в done как обычно.
    done: list[int] = []
    monkeypatch.setattr(boost, "mark_playtime_done", done.append)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )
    monkeypatch.setattr(
        boost,
        "idle_and_split_survivors",
        lambda active, idle, on_failed=None: (list(active.keys()), []),
    )

    games = [{"appid": 10, "name": "A", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg(), persist_done=True)

    assert done == [10]


def test_boost_loop_known_failure_not_written_to_skip(monkeypatch):
    # H1: провал KNOWN-игры НЕ пишется в skip (истина по Steam API — ретрай на
    # следующем прогоне); в skip уходят только unknown-провалы.
    done: list[int] = []
    skip: list[int] = []
    monkeypatch.setattr(boost, "mark_playtime_done", done.append)
    monkeypatch.setattr(boost, "mark_playtime_skip", skip.append)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost, "send_telegram", lambda *a, **k: None)
    monkeypatch.setattr(boost, "kill_all_sam_games", lambda: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )

    def fake_idle(active, idle, on_failed=None):
        on_failed(99)  # known-игра провалилась (транзиентно)
        on_failed(30)  # unknown-игра провалилась
        return ([], [99, 30])

    monkeypatch.setattr(boost, "idle_and_split_survivors", fake_idle)

    games = [
        {"appid": 99, "name": "K", "playtime_forever": 1, "known": True},
        {"appid": 30, "name": "U", "playtime_forever": 0, "known": False},
    ]
    boost._boost_loop(games, _cfg())

    assert 99 not in skip  # known-провал НЕ похоронен в skip
    assert skip == [30]  # только unknown-провал
    assert done == []  # провалы не идут в done


def test_boost_loop_notifies_telegram_on_finish(monkeypatch):
    # Завершение батча шлёт Telegram-уведомление (рядом с toast).
    tg: list[str] = []
    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(
        boost, "send_telegram", lambda text, cfg: tg.append(text), raising=False
    )
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )
    monkeypatch.setattr(
        boost,
        "idle_and_split_survivors",
        lambda active, idle, on_failed=None: ([10], []),
    )

    games = [{"appid": 10, "name": "A", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg())

    assert tg and "обработано" in tg[-1]


def test_boost_loop_ctrl_c_kills_active_without_marking_done(monkeypatch):
    # Инвариант: Ctrl+C убивает активные, но НЕ пишет done.
    done: list[int] = []
    killed: list[object] = []
    monkeypatch.setattr(boost, "mark_playtime_done", done.append)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost, "kill_process", killed.append)
    # Замокать, иначе тест зовёт настоящий win32 TerminateProcess по всем
    # SAM.Game.exe — убьёт активный boost/farm, если он идёт во время pytest.
    monkeypatch.setattr(boost, "kill_all_sam_games", lambda: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )

    def boom(active, idle, on_failed=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(boost, "idle_and_split_survivors", boom)

    games = [
        {"appid": 10, "name": "A", "playtime_forever": 0, "known": False},
        {"appid": 20, "name": "B", "playtime_forever": 0, "known": False},
    ]
    boost._boost_loop(games, _cfg())  # не должно пробросить наружу

    assert done == []  # ничего не помечено done
    assert len(killed) == 2  # все активные убиты


def test_boost_loop_ctrl_c_after_failure_keeps_skip(monkeypatch):
    # Провал задетектирован и записан в skip во время idle, ЗАТЕМ Ctrl+C →
    # skip сохранён (on_failed пишет в момент детекции, не после возврата).
    skip: list[int] = []
    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", skip.append)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost, "kill_process", lambda p: None)
    monkeypatch.setattr(boost, "kill_all_sam_games", lambda: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )

    def fail_then_interrupt(active, idle, on_failed=None):
        on_failed(30)  # провал зафиксирован в skip
        raise KeyboardInterrupt  # затем прерывание

    monkeypatch.setattr(boost, "idle_and_split_survivors", fail_then_interrupt)

    games = [{"appid": 30, "name": "C", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg())

    assert skip == [30]  # skip пережил Ctrl+C


def test_boost_loop_ctrl_c_during_launch_kills_all_sam(monkeypatch):
    # Ctrl+C во время staggered-запуска батча: процессы уже стартовали, но ещё
    # не в active → обычный проход их не тронет. Страховка kill_all_sam_games
    # добивает все SAM.Game.exe, чтобы не осиротить.
    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost, "kill_process", lambda p: None)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    swept: list[bool] = []
    monkeypatch.setattr(boost, "kill_all_sam_games", lambda: swept.append(True))

    def launch_interrupts(exe, games, stagger):
        raise KeyboardInterrupt  # прерывание во время запуска батча

    monkeypatch.setattr(boost, "launch_games_staggered", launch_interrupts)

    games = [{"appid": 10, "name": "A", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg())  # не должно пробросить наружу

    assert swept == [True]  # страховка добила процессы


def test_boost_loop_kill_process_raises_still_sweeps_and_reports(monkeypatch):
    # RA-C: не-KI из kill_process в teardown (Windows proc.kill()→PermissionError
    # в гонке терминации) НЕ должен пропустить бэкстоп kill_all_sam_games (сироты)
    # и НЕ должен пропустить честный _report_result.
    swept: list[bool] = []
    tg: list[str] = []

    def bad_kill(proc):
        raise PermissionError("terminate race")

    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost, "kill_process", bad_kill)
    monkeypatch.setattr(boost, "kill_all_sam_games", lambda: swept.append(True))
    monkeypatch.setattr(
        boost, "send_telegram", lambda text, cfg: tg.append(text)
    )
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )
    monkeypatch.setattr(
        boost,
        "idle_and_split_survivors",
        lambda active, idle, on_failed=None: (list(active.keys()), []),
    )

    games = [{"appid": 10, "name": "A", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg())  # не должно пробросить PermissionError

    assert swept == [True]  # бэкстоп добил сирот несмотря на сбой kill_process
    assert tg and "обработано" in tg[-1]  # честный отчёт не потерян


def test_boost_loop_kill_all_raises_still_reports(monkeypatch):
    # RA-C: не-KI из самого kill_all_sam_games НЕ должен пропустить _report_result.
    tg: list[str] = []

    def bad_sweep():
        raise OSError("win32 sweep fail")

    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(boost, "kill_process", lambda p: None)
    monkeypatch.setattr(boost, "kill_all_sam_games", bad_sweep)
    monkeypatch.setattr(
        boost, "send_telegram", lambda text, cfg: tg.append(text)
    )
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )
    monkeypatch.setattr(
        boost,
        "idle_and_split_survivors",
        lambda active, idle, on_failed=None: (list(active.keys()), []),
    )

    games = [{"appid": 10, "name": "A", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg())  # не должно пробросить OSError

    assert tg  # отчёт не потерян даже при сбое бэкстопа


def test_boost_loop_second_ctrl_c_during_teardown_retries_sweep(monkeypatch):
    # C5: второй Ctrl+C во время finally-свипа не обрывает уборку — повторяем.
    calls = {"sweep": 0}

    def flaky_sweep():
        calls["sweep"] += 1
        if calls["sweep"] == 1:
            raise KeyboardInterrupt  # второй Ctrl+C прямо во время свипа

    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "kill_process", lambda p: None)
    monkeypatch.setattr(boost, "kill_all_sam_games", flaky_sweep)
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )

    def boom(active, idle, on_failed=None):
        raise KeyboardInterrupt  # первый Ctrl+C

    monkeypatch.setattr(boost, "idle_and_split_survivors", boom)

    games = [{"appid": 10, "name": "A", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg())  # НЕ должно пробросить KeyboardInterrupt

    assert calls["sweep"] >= 2  # свип повторён после прерывания


def test_boost_loop_multi_batch_pauses_between_not_after(monkeypatch):
    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    sleeps: list[float] = []
    monkeypatch.setattr(boost.time, "sleep", sleeps.append)
    launched: list[list[int]] = []

    def fake_launch(exe, games, stagger):
        launched.append([appid for appid, _ in games])
        return {appid: object() for appid, _ in games}

    monkeypatch.setattr(boost, "launch_games_staggered", fake_launch)
    monkeypatch.setattr(
        boost,
        "idle_and_split_survivors",
        lambda active, idle, on_failed=None: (list(active.keys()), []),
    )

    games = [
        {"appid": i, "name": str(i), "playtime_forever": 0, "known": False}
        for i in (10, 20, 30)
    ]
    boost._boost_loop(games, _cfg(playtime_concurrent_games=2))

    # 3 игры по 2 → два батча: [10, 20] и [30]
    assert launched == [[10, 20], [30]]
    # _PAUSE_AFTER_KILL ровно один раз — между батчами, не после последнего
    assert sleeps == [boost._PAUSE_AFTER_KILL]


def test_boost_loop_non_ki_exception_sweeps_and_no_done(monkeypatch):
    # H2: любое НЕ-KeyboardInterrupt исключение в батче → finally добивает
    # процессы (kill_all_sam_games), done не пишется, наружу не пробрасывается.
    done: list[int] = []
    swept: list[bool] = []
    monkeypatch.setattr(boost, "mark_playtime_done", done.append)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "kill_process", lambda p: None)
    monkeypatch.setattr(boost, "kill_all_sam_games", lambda: swept.append(True))
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )

    def boom(active, idle, on_failed=None):
        raise ValueError("сбой в середине батча")

    monkeypatch.setattr(boost, "idle_and_split_survivors", boom)

    games = [{"appid": 10, "name": "A", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg())  # НЕ должно пробросить ValueError

    assert swept == [True]  # свип сработал
    assert done == []  # ошибка не пишет done


def test_boost_loop_ctrl_c_report_no_success_mark(monkeypatch):
    # M1: Ctrl+C НЕ даёт success-✅ в Telegram-отчёте.
    tg: list[str] = []
    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "kill_process", lambda p: None)
    monkeypatch.setattr(
        boost, "send_telegram", lambda text, cfg: tg.append(text)
    )
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )

    def boom(active, idle, on_failed=None):
        raise KeyboardInterrupt

    monkeypatch.setattr(boost, "idle_and_split_survivors", boom)

    games = [{"appid": 10, "name": "A", "playtime_forever": 0, "known": False}]
    boost._boost_loop(games, _cfg())

    assert tg and "✅" not in tg[-1]  # не success на прерывании


def test_boost_loop_all_failed_report_no_success_mark(monkeypatch):
    # M1: когда все игры провалились — не success-✅, набито 0, а не "N/N".
    tg: list[str] = []
    monkeypatch.setattr(boost, "mark_playtime_done", lambda a: None)
    monkeypatch.setattr(boost, "mark_playtime_skip", lambda a: None)
    monkeypatch.setattr(boost, "kill_process", lambda p: None)
    monkeypatch.setattr(
        boost, "send_telegram", lambda text, cfg: tg.append(text)
    )
    monkeypatch.setattr(boost.time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(
        boost,
        "launch_games_staggered",
        lambda exe, games, stagger: {appid: object() for appid, _ in games},
    )
    # все 2 игры провалились: survivors=[], failed=[10,20]
    monkeypatch.setattr(
        boost,
        "idle_and_split_survivors",
        lambda active, idle, on_failed=None: ([], list(active.keys())),
    )

    games = [
        {"appid": 10, "name": "A", "playtime_forever": 0, "known": False},
        {"appid": 20, "name": "B", "playtime_forever": 0, "known": False},
    ]
    boost._boost_loop(games, _cfg())

    assert tg and "✅" not in tg[-1]  # провал всех — не success


# ── RA-10: прямая матрица _report_result (все 4 ветки status × failed) ────────


def _capture_report(monkeypatch):  # type: ignore[no-untyped-def]
    tg: list[str] = []
    monkeypatch.setattr(boost, "toast", lambda *a, **k: None)
    monkeypatch.setattr(
        boost, "send_telegram", lambda text, cfg: tg.append(text)
    )
    return tg


def test_report_result_ok_clean_is_success(monkeypatch):
    tg = _capture_report(monkeypatch)
    boost._report_result("ok", boosted=5, failed=0, total=5, cfg=object())
    assert "✅" in tg[-1] and "готово" in tg[-1]


def test_report_result_ok_with_failures_is_warning(monkeypatch):
    tg = _capture_report(monkeypatch)
    boost._report_result("ok", boosted=3, failed=2, total=5, cfg=object())
    assert "✅" not in tg[-1] and "оговорками" in tg[-1]


def test_report_result_interrupted_is_warning(monkeypatch):
    tg = _capture_report(monkeypatch)
    boost._report_result(
        "interrupted", boosted=1, failed=0, total=5, cfg=object()
    )
    assert "✅" not in tg[-1] and "Ctrl+C" in tg[-1]


def test_report_result_error_is_warning(monkeypatch):
    # RA-10: ветка error раньше не пиннилась прямым ассертом честности —
    # регрессия ok=True на error-пути прошла бы весь сьют.
    tg = _capture_report(monkeypatch)
    boost._report_result("error", boosted=0, failed=0, total=5, cfg=object())
    assert "✅" not in tg[-1] and "ошибкой" in tg[-1]
