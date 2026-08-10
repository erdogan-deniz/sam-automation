"""Тесты оркестрации main() achievements/farm — порядок resolve/validate.

Зеркало test_boost_main.py: тот же класс бага (RA-B), обнаруженный здесь
живьём при аудите — farm.py, в отличие от boost/scan/add_free/wishlist_add,
никогда не резолвил vanity-имя/URL steam_id перед validate().
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from app.exceptions import SAMLaunchError

_FARM_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "achievements" / "farm.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "farm_ach_under_test_main", _FARM_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


farm = _load()


def _cfg(**over: object) -> SimpleNamespace:
    base = {
        "steam_api_key": "k",
        "steam_id": "gabelogannewell",
        "sam_game_exe_path": "x",
        "launch_delay": 0,
    }
    base.update(over)
    return SimpleNamespace(**base)


def _stub_main_deps(monkeypatch, cfg, order, seen) -> None:  # type: ignore[no-untyped-def]
    """Мокает внешние зависимости main(), записывает порядок resolve/validate.

    check_steam_running → False, поэтому main дойдёт до sys.exit(1) сразу
    после resolve/validate/_prepare_progress, не трогая SAM.
    """
    monkeypatch.setattr(sys, "argv", ["farm.py"])
    monkeypatch.setattr(farm, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(farm, "load_config", lambda: cfg)
    monkeypatch.setattr(farm, "acquire_run_lock", lambda name: None)
    monkeypatch.setattr(farm.atexit, "register", lambda f: None)
    monkeypatch.setattr(farm, "_prepare_progress", lambda args: None)
    monkeypatch.setattr(farm, "check_steam_running", lambda: False)

    def fake_resolve(api_key, sid):  # type: ignore[no-untyped-def]
        order.append("resolve")
        return "76561197960287930"

    def fake_validate(c):  # type: ignore[no-untyped-def]
        order.append("validate")
        seen["validate_steam_id"] = c.steam_id

    monkeypatch.setattr(farm, "resolve_steam_id", fake_resolve)
    monkeypatch.setattr(farm, "validate", fake_validate)


def test_main_resolves_steam_id_before_validate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # RA-B (тот же класс, что в boost/scan/add_free/wishlist_add): validate
    # шлёт steam_id в GetPlayerSummaries, которому нужен числовой ID64. farm.py
    # никогда не резолвил vanity/URL → ложное «API key invalid» для любого
    # пользователя, настроившего steam_id как vanity-имя/URL (документированный
    # README формат).
    order: list[str] = []
    seen: dict[str, str] = {}
    _stub_main_deps(monkeypatch, _cfg(steam_id="gabelogannewell"), order, seen)

    with pytest.raises(SystemExit):
        farm.main()

    assert order == ["resolve", "validate"]  # resolve ПЕРЕД validate
    assert seen["validate_steam_id"] == "76561197960287930"


def test_main_empty_steam_id_not_resolved(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Пустой steam_id НЕ резолвим (лишний сетевой вызов) — пусть validate
    # выдаст локальную ошибку «steam_id is missing».
    order: list[str] = []
    seen: dict[str, str] = {}
    _stub_main_deps(monkeypatch, _cfg(steam_id=""), order, seen)

    with pytest.raises(SystemExit):
        farm.main()

    assert "resolve" not in order  # пустой id не резолвится
    assert order == ["validate"]


def _stub_main_deps_through_launch(monkeypatch, cfg, calls) -> None:  # type: ignore[no-untyped-def]
    """Мокает main() дальше — до launch_picker включительно.

    Не мокает launch_picker/SetThreadExecutionState — тест сам решает их
    поведение, чтобы проверить guard-обвязку вокруг launch_picker и
    факт вызова SetThreadExecutionState перед основным циклом.
    """
    monkeypatch.setattr(sys, "argv", ["farm.py"])
    monkeypatch.setattr(farm, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(farm, "load_config", lambda: cfg)
    monkeypatch.setattr(farm, "acquire_run_lock", lambda name: None)
    monkeypatch.setattr(farm.atexit, "register", lambda f: None)
    monkeypatch.setattr(farm, "_prepare_progress", lambda args: None)
    monkeypatch.setattr(farm, "resolve_steam_id", lambda key, sid: sid)
    monkeypatch.setattr(farm, "validate", lambda c: None)
    monkeypatch.setattr(farm, "check_steam_running", lambda: True)
    monkeypatch.setattr(farm, "ensure_sam", lambda path: path)
    monkeypatch.setattr(farm, "load_game_ids", lambda cfg: [730])
    monkeypatch.setattr(farm, "_apply_resume_filter", lambda ids: ids)
    monkeypatch.setattr(
        farm, "prevent_idle_sleep", lambda: calls.append("execstate")
    )


def test_main_launch_picker_failure_exits_cleanly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # [Medium, docs/prompts/achievements-farm.md] launch_picker — единственный
    # из 4 похожих вызовов в main() (acquire_run_lock/resolve_steam_id/
    # ensure_sam тоже могут кинуть) БЕЗ try/except: сбой (SAMLaunchError/
    # SAMConnectionError) давал сырой трейсбек вместо чистого exit(1).
    calls: list[object] = []
    _stub_main_deps_through_launch(monkeypatch, _cfg(), calls)

    def boom(path, launch_delay=0):  # type: ignore[no-untyped-def]
        raise SAMLaunchError("SAM.Picker.exe не найден")

    monkeypatch.setattr(farm, "launch_picker", boom)

    with pytest.raises(SystemExit) as exc:
        farm.main()

    assert exc.value.code == 1
    assert "execstate" not in calls  # не дошли до prevent_idle_sleep


def test_main_prevents_idle_sleep_before_main_loop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Слепая зона аудита: заблокированный/уснувший по простою экран роняет
    # pywinauto-клики (RuntimeError «нет активного рабочего стола») в КАЖДОЙ
    # следующей игре — реальная волна ошибок на многочасовом прогоне.
    # SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED|ES_DISPLAY_REQUIRED)
    # не спасает от ручного Win+L, но закрывает самый реалистичный триггер —
    # авто-блокировку по таймауту простоя.
    calls: list[object] = []
    cfg = _cfg(max_consecutive_errors=5, between_games_delay=0)
    _stub_main_deps_through_launch(monkeypatch, cfg, calls)
    monkeypatch.setattr(
        farm, "launch_picker", lambda path, launch_delay=0: (object(), object())
    )
    monkeypatch.setattr(farm, "load_game_names", lambda: {})
    monkeypatch.setattr(farm, "_process_one_game", lambda *a, **k: None)
    monkeypatch.setattr(farm, "toast", lambda *a, **k: None)
    monkeypatch.setattr(farm, "send_telegram", lambda *a, **k: None)

    farm.main()  # не должен бросить — полностью застублен до конца

    assert calls.count("execstate") == 1


def test_main_resolve_failure_exits_cleanly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Сбой резолва (сеть/неуспех vanity) → чистый sys.exit(1), не сырой
    # трейсбек, и до validate НЕ доходим.
    order: list[str] = []
    seen: dict[str, str] = {}
    _stub_main_deps(monkeypatch, _cfg(steam_id="badvanity"), order, seen)

    def boom(api_key, sid):  # type: ignore[no-untyped-def]
        raise RuntimeError("vanity не резолвится")

    monkeypatch.setattr(farm, "resolve_steam_id", boom)

    with pytest.raises(SystemExit) as exc:
        farm.main()

    assert exc.value.code == 1
    assert "validate" not in order  # до validate не дошли
