"""Тесты Fast-mode цикла scripts/cards/farm.py::_farm_loop.

Механика дропов: карта выдаётся при коллапсе in-game состояния в НОЛЬ
(закрыл все окна). Поэтому цикл должен УБИТЬ ВСЕ игры разом, дать паузу
на сброс, затем перечитать остатки — а не kill+relaunch по одной
(при котором аккаунт всегда в игре и сброс не срабатывает).

Фейки: без реального subprocess/HTTP/sleep. FakeProc несёт appid,
чтобы kill_process мог его залогировать.
"""

from __future__ import annotations

import importlib.util
from collections import deque
from pathlib import Path
from types import ModuleType, SimpleNamespace

_FARM_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "cards" / "farm.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "cards_farm_loop_under_test", _FARM_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeProc:
    def __init__(self, appid: int) -> None:
        self.appid = appid
        self.pid = 10_000 + appid

    def poll(self) -> None:
        return None


def _run(
    check_script: dict[int, list[int]],
    games: list[tuple[int, int]],
    max_concurrent: int = 5,
    interrupt_on_idle: bool = False,
    kill_raises_for: set[int] | None = None,
    launch_raises_for: set[int] | None = None,
    refresh_cookies: dict | None = None,
) -> list[tuple[str, object]]:
    """Гоняет _farm_loop на фейках, возвращает список событий по порядку."""
    farm = _load()
    events: list[tuple[str, object]] = []
    scripts = {aid: deque(vals) for aid, vals in check_script.items()}
    kill_raises = kill_raises_for or set()
    launch_raises = launch_raises_for or set()
    idle_secs = 10 * 60  # cfg.card_check_interval * 60

    def fake_launch(exe: str, appid: int) -> _FakeProc:
        if appid in launch_raises:
            raise RuntimeError(f"launch boom {appid}")
        events.append(("launch", appid))
        return _FakeProc(appid)

    def fake_kill(proc: _FakeProc) -> None:
        events.append(("kill", proc.appid))
        if proc.appid in kill_raises:
            raise RuntimeError(f"kill boom {proc.appid}")

    def fake_check(cookies: object, sid: str, appid: int) -> int:
        events.append(("check", appid))
        return scripts[appid].popleft()

    def fake_done(appid: int) -> None:
        events.append(("done", appid))

    def fake_sleep(s: float) -> None:
        events.append(("sleep", s))
        if interrupt_on_idle and s == idle_secs:
            raise KeyboardInterrupt

    farm.launch_game = fake_launch  # type: ignore[assignment]
    farm.kill_process = fake_kill  # type: ignore[assignment]
    farm.check_cards_remaining = fake_check  # type: ignore[assignment]
    farm.mark_card_done = fake_done  # type: ignore[assignment]
    farm.load_game_names = lambda: {}  # type: ignore[assignment]
    farm.toast = lambda title, msg: events.append(("toast", msg))  # type: ignore[assignment]
    farm.send_telegram = lambda text, cfg: events.append(("telegram", text))  # type: ignore[assignment]
    farm.kill_all_sam_games = lambda: events.append(("sweep", None))  # type: ignore[assignment]

    def fake_get_cookies(
        username: str, interactive: bool = True
    ) -> dict | None:
        events.append(("refresh", interactive))
        return refresh_cookies

    farm.get_web_cookies = fake_get_cookies  # type: ignore[assignment]
    farm.time = SimpleNamespace(sleep=fake_sleep)  # type: ignore[assignment]

    cfg = SimpleNamespace(
        max_concurrent_games=max_concurrent,
        card_check_interval=10,
        sam_game_exe_path="SAM.Game.exe",
        steam_id="76561190000000000",
    )
    farm._farm_loop(games, cfg, {}, "76561190000000000")
    return events


def _idx(events: list[tuple[str, object]], kind: str) -> list[int]:
    return [i for i, (k, _) in enumerate(events) if k == kind]


def test_kills_all_before_rechecking() -> None:
    """Все активные игры убиты ДО первой перепроверки остатков."""
    events = _run({111: [0], 222: [0]}, [(111, 2), (222, 3)])

    last_kill = max(_idx(events, "kill"))
    first_check = min(_idx(events, "check"))
    assert last_kill < first_check, f"kill должны идти до check: {events}"


def test_flush_pause_between_kill_and_recheck() -> None:
    """Между убийством всех и перепроверкой есть пауза-flush."""
    farm = _load()
    events = _run({111: [0], 222: [0]}, [(111, 2), (222, 3)])

    last_kill = max(_idx(events, "kill"))
    first_check = min(_idx(events, "check"))
    between = [
        v for (k, v) in events[last_kill + 1 : first_check] if k == "sleep"
    ]
    assert farm._FLUSH_PAUSE_SECONDS in between, (
        f"ожидалась пауза {farm._FLUSH_PAUSE_SECONDS}s между kill и check: "
        f"{events}"
    )


def test_survivors_requeued_and_done_marked() -> None:
    """Игра с 0 остатком — done; с остатком >0 — перезапуск в след. цикле."""
    events = _run(
        {111: [0], 222: [3, 0]},
        [(111, 2), (222, 3)],
    )

    done = [aid for (k, aid) in events if k == "done"]
    launches = [aid for (k, aid) in events if k == "launch"]

    assert 111 in done
    assert 222 in done
    assert launches.count(111) == 1  # done в цикле 1 — не перезапускалась
    assert launches.count(222) == 2  # выжила в цикле 1 — перезапущена


def test_minus_one_retries_then_leaves_rotation() -> None:
    """remaining=-1 накапливает failures; на _MAX_CHECK_FAILURES бросается."""
    farm = _load()
    n = farm._MAX_CHECK_FAILURES
    events = _run({111: [-1] * n}, [(111, 2)], max_concurrent=1)

    done = [aid for (k, aid) in events if k == "done"]
    launches = [aid for (k, aid) in events if k == "launch"]
    checks = [aid for (k, aid) in events if k == "check"]

    assert done == []  # НЕ помечается done (честность отчёта)
    assert len(checks) == n  # бросили ровно на n-й проверке (цикл завершился)
    # перезапущена после каждой из первых n-1 неудач + начальный запуск
    assert launches.count(111) == n


def test_minus_one_failures_reset_by_success() -> None:
    """Успешная проверка сбрасывает счётчик — нет преждевременного done."""
    farm = _load()
    n = farm._MAX_CHECK_FAILURES
    # n-1 отказов, затем 0 → должна закрыться как done, но НЕ по лимиту неудач
    script = [-1] * (n - 1) + [0]
    events = _run({111: script}, [(111, 2)], max_concurrent=1)

    done = [aid for (k, aid) in events if k == "done"]
    assert done == [111]  # закрылась по remaining==0, счётчик не переполнился


def test_stall_guard_terminates_stuck_game() -> None:
    """Игра с неубывающим остатком бросается и цикл завершается (не виснет)."""
    farm = _load()
    stuck = [5] * (farm._MAX_NO_PROGRESS + 5)
    events = _run({111: stuck}, [(111, 5)], max_concurrent=1)

    done = [aid for (k, aid) in events if k == "done"]
    # цикл завершился (не исчерпал deque → не завис) и НЕ пометил игру done
    assert 111 not in done


def test_batching_max_concurrent_one() -> None:
    """max_concurrent=1: игры фармятся по одной, каждая ровно один раз."""
    events = _run(
        {111: [0], 222: [0], 333: [0]},
        [(111, 1), (222, 1), (333, 1)],
        max_concurrent=1,
    )

    done = [aid for (k, aid) in events if k == "done"]
    launches = [aid for (k, aid) in events if k == "launch"]

    assert done == [111, 222, 333]
    assert launches == [111, 222, 333]  # каждая запущена один раз, по очереди


def test_keyboard_interrupt_kills_all_active() -> None:
    """Ctrl+C во время idle — finally закрывает все активные игры."""
    events = _run(
        {111: [0], 222: [0]},
        [(111, 2), (222, 3)],
        interrupt_on_idle=True,
    )

    killed = {aid for (k, aid) in events if k == "kill"}
    assert killed == {111, 222}


def test_finally_kill_guard_isolates_failure() -> None:
    """Сбой закрытия одной игры в finally не мешает закрыть остальные."""
    events = _run(
        {111: [0], 222: [0]},
        [(111, 2), (222, 3)],
        interrupt_on_idle=True,
        kill_raises_for={111},
    )

    killed = [aid for (k, aid) in events if k == "kill"]
    assert 222 in killed  # не осиротела из-за падения kill(111)


def _last_toast(events: list[tuple[str, object]]) -> str:
    msgs = [m for (k, m) in events if k == "toast"]
    return str(msgs[-1]) if msgs else ""


def _last_telegram(events: list[tuple[str, object]]) -> str:
    msgs = [m for (k, m) in events if k == "telegram"]
    return str(msgs[-1]) if msgs else ""


def test_stall_giveup_does_not_mark_done_and_flags_toast() -> None:
    """Застрявшая игра НЕ помечается done; финальный тост — с оговоркой."""
    farm = _load()
    stuck = [5] * (farm._MAX_NO_PROGRESS + 5)
    events = _run({111: stuck}, [(111, 5)], max_concurrent=1)

    done = [aid for (k, aid) in events if k == "done"]
    assert 111 not in done  # застряла — не «выполнена»
    assert "Card farming завершён" != _last_toast(events)  # тост не «чистый»


def test_minus_one_giveup_does_not_mark_done_and_flags_toast() -> None:
    """Неопределимая (-1) игра НЕ помечается done; тост — с оговоркой."""
    farm = _load()
    n = farm._MAX_CHECK_FAILURES
    events = _run({111: [-1] * n}, [(111, 2)], max_concurrent=1)

    done = [aid for (k, aid) in events if k == "done"]
    assert 111 not in done  # не смогли проверить — не «выполнена»
    assert "Card farming завершён" != _last_toast(events)


def test_clean_completion_uses_plain_toast() -> None:
    """Все игры честно закрылись (0) → обычный тост без оговорок."""
    events = _run({111: [0], 222: [0]}, [(111, 2), (222, 3)])

    done = {aid for (k, aid) in events if k == "done"}
    assert done == {111, 222}
    assert _last_toast(events) == "Card farming завершён"


def test_clean_completion_also_sends_telegram() -> None:
    """Чистое завершение шлёт и Telegram-уведомление (рядом с toast)."""
    events = _run({111: [0], 222: [0]}, [(111, 2), (222, 3)])

    assert "завершён" in _last_telegram(events)


def test_finally_sweeps_orphans_on_interrupt() -> None:
    """При Ctrl+C finally вызывает kill_all_sam_games (страховка от сирот)."""
    events = _run(
        {111: [0], 222: [0]},
        [(111, 2), (222, 3)],
        interrupt_on_idle=True,
    )

    assert ("sweep", None) in events


def test_open_next_skips_failed_launch() -> None:
    """Сбой launch_game одной игры не рушит прогон — она пропускается."""
    events = _run(
        {111: [0], 333: [0]},
        [(111, 1), (222, 1), (333, 1)],
        max_concurrent=1,
        launch_raises_for={222},
    )

    launches = [aid for (k, aid) in events if k == "launch"]
    done = {aid for (k, aid) in events if k == "done"}
    assert 222 not in launches  # упавший запуск пропущен
    assert done == {111, 333}  # остальные отфармлены, прогон не упал


def test_collapse_kill_failure_does_not_abort_cycle() -> None:
    """Сбой kill в фазе коллапса не прерывает перечитку и прогон."""
    events = _run(
        {111: [0], 222: [0]},
        [(111, 2), (222, 2)],
        kill_raises_for={111},
    )

    done = {aid for (k, aid) in events if k == "done"}
    assert done == {111, 222}  # обе перечитаны и закрыты, несмотря на сбой kill


def test_interrupted_run_uses_interrupted_toast() -> None:
    """Ctrl+C-прогон НЕ рапортует success — тост «прерван»."""
    events = _run(
        {111: [0], 222: [0]},
        [(111, 2), (222, 3)],
        interrupt_on_idle=True,
    )

    assert "прерван" in _last_toast(events).lower()
    assert _last_toast(events) != "Card farming завершён"


def test_failed_launch_flagged_in_toast() -> None:
    """Игра, которую не удалось запустить, отражается в тосте с оговоркой."""
    events = _run(
        {111: [0], 333: [0]},
        [(111, 1), (222, 1), (333, 1)],
        max_concurrent=1,
        launch_raises_for={222},
    )

    assert "оговорками" in _last_toast(events)
    assert _last_toast(events) != "Card farming завершён"


def test_cookie_refresh_on_minus_one() -> None:
    """-1 (протухли куки) → обновить куки неинтерактивно и перечитать остаток.

    222: первый check даёт -1 → рефреш кук → повторный check даёт 0 → done.
    Игра НЕ должна уйти в unverified, тост — чистый.
    """
    events = _run(
        {222: [-1, 0]},
        [(222, 3)],
        refresh_cookies={"steamLoginSecure": "fresh"},
    )

    assert ("refresh", False) in events  # обновление именно неинтерактивное
    assert ("done", 222) in events  # перечитанный 0 → помечен done
    assert _last_toast(events) == "Card farming завершён"  # без «оговорок»


def test_no_cookie_refresh_when_check_ok() -> None:
    """Без -1 куки не трогаем (нет лишних вызовов get_web_cookies)."""
    events = _run({222: [0]}, [(222, 2)])

    assert ("refresh", False) not in events
