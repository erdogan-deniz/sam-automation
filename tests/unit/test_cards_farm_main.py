"""Тесты оркестрации main() cards/farm — порядок resolve/validate.

Зеркало test_boost_main.py/test_farm_main.py: тот же класс бага (RA-B) —
cards/farm.py резолвил steam_id (vanity/URL → ID64) ПОСЛЕ validate(), а не
до, в отличие от остальных четырёх SAM/library-скриптов проекта.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_CARDS_FARM_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "cards" / "farm.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "cards_farm_under_test_main", _CARDS_FARM_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cards_farm = _load()


def _cfg(**over: object) -> SimpleNamespace:
    base = {
        "steam_api_key": "k",
        "steam_id": "gabelogannewell",
        "sam_game_exe_path": "x",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _stub_main_deps(monkeypatch, cfg, order, seen) -> None:  # type: ignore[no-untyped-def]
    """Мокает внешние зависимости main(), записывает порядок resolve/validate.

    check_steam_running → False, поэтому main дойдёт до sys.exit(1) сразу
    после resolve/validate, не трогая SAM/веб-куки.
    """
    monkeypatch.setattr(sys, "argv", ["farm.py"])
    monkeypatch.setattr(cards_farm, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(cards_farm, "load_config", lambda: cfg)
    monkeypatch.setattr(cards_farm, "acquire_run_lock", lambda name: None)
    monkeypatch.setattr(cards_farm.atexit, "register", lambda f: None)
    monkeypatch.setattr(cards_farm, "check_steam_running", lambda: False)

    def fake_resolve(api_key, sid):  # type: ignore[no-untyped-def]
        order.append("resolve")
        return "76561197960287930"

    def fake_validate(c):  # type: ignore[no-untyped-def]
        order.append("validate")
        seen["validate_steam_id"] = c.steam_id

    monkeypatch.setattr(cards_farm, "resolve_steam_id", fake_resolve)
    monkeypatch.setattr(cards_farm, "validate", fake_validate)


def test_main_resolves_steam_id_before_validate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # RA-B: validate шлёт steam_id в GetPlayerSummaries, которому нужен
    # числовой ID64. cards/farm.py резолвил vanity/URL ПОСЛЕ validate —
    # ложное «API key invalid» для любого пользователя с vanity/URL steam_id
    # (документированный README формат) до того, как резолв вообще случится.
    order: list[str] = []
    seen: dict[str, str] = {}
    _stub_main_deps(monkeypatch, _cfg(steam_id="gabelogannewell"), order, seen)

    with pytest.raises(SystemExit):
        cards_farm.main()

    assert order == ["resolve", "validate"]  # resolve ПЕРЕД validate
    assert seen["validate_steam_id"] == "76561197960287930"


def test_main_empty_steam_id_not_resolved(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Пустой steam_id НЕ резолвим (лишний сетевой вызов) — пусть validate
    # выдаст локальную ошибку «steam_id is missing».
    order: list[str] = []
    seen: dict[str, str] = {}
    _stub_main_deps(monkeypatch, _cfg(steam_id=""), order, seen)

    with pytest.raises(SystemExit):
        cards_farm.main()

    assert "resolve" not in order  # пустой id не резолвится
    assert order == ["validate"]


def test_main_resolve_failure_exits_cleanly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Сбой резолва (сеть/неуспех vanity) → чистый sys.exit(1), не сырой
    # трейсбек, и до validate НЕ доходим.
    order: list[str] = []
    seen: dict[str, str] = {}
    _stub_main_deps(monkeypatch, _cfg(steam_id="badvanity"), order, seen)

    def boom(api_key, sid):  # type: ignore[no-untyped-def]
        raise RuntimeError("vanity не резолвится")

    monkeypatch.setattr(cards_farm, "resolve_steam_id", boom)

    with pytest.raises(SystemExit) as exc:
        cards_farm.main()

    assert exc.value.code == 1
    assert "validate" not in order  # до validate не дошли
