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
) -> list[tuple[str, object]]:
    """Гоняет _farm_loop на фейках, возвращает список событий по порядку."""
    farm = _load()
    events: list[tuple[str, object]] = []
    scripts = {aid: deque(vals) for aid, vals in check_script.items()}

    def fake_launch(exe: str, appid: int) -> _FakeProc:
        events.append(("launch", appid))
        return _FakeProc(appid)

    def fake_kill(proc: _FakeProc) -> None:
        events.append(("kill", proc.appid))

    def fake_check(cookies: object, sid: str, appid: int) -> int:
        events.append(("check", appid))
        return scripts[appid].popleft()

    def fake_done(appid: int) -> None:
        events.append(("done", appid))

    farm.launch_game = fake_launch  # type: ignore[assignment]
    farm.kill_process = fake_kill  # type: ignore[assignment]
    farm.check_cards_remaining = fake_check  # type: ignore[assignment]
    farm.mark_card_done = fake_done  # type: ignore[assignment]
    farm.load_game_names = lambda: {}  # type: ignore[assignment]
    farm.toast = lambda *a, **k: None  # type: ignore[assignment]
    farm.time = SimpleNamespace(  # type: ignore[assignment]
        sleep=lambda s: events.append(("sleep", s))
    )

    cfg = SimpleNamespace(
        max_concurrent_games=max_concurrent,
        card_check_interval=10,
        sam_game_exe_path="SAM.Game.exe",
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
