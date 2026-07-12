"""Тесты оркестрации main() boost — порядок resolve/validate и пр."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_BOOST_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "playtime" / "boost.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "boost_under_test_main", _BOOST_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


boost = _load()


def _cfg(**over: object) -> SimpleNamespace:
    base = {
        "steam_api_key": "k",
        "steam_id": "gabelogannewell",
        "sam_game_exe_path": "x",
        "playtime_concurrent_games": 10,
        "playtime_idle_duration": 1,
        "playtime_target_minutes": 3,
        "launch_stagger": 0.0,
        "exclude_ids": [],
    }
    base.update(over)
    return SimpleNamespace(**base)


def _stub_main_deps(monkeypatch, cfg, order, seen) -> None:  # type: ignore[no-untyped-def]
    """Мокает внешние зависимости main(), records порядок resolve/validate.

    _fetch_targets → пустые цели, поэтому main дойдёт до sys.exit(0) сразу после
    resolve/validate, не трогая run-loop.
    """
    monkeypatch.setattr(sys, "argv", ["boost.py"])
    monkeypatch.setattr(boost, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(boost, "load_config", lambda: cfg)
    monkeypatch.setattr(boost, "check_steam_running", lambda: True)
    monkeypatch.setattr(boost, "ensure_sam", lambda p: p)
    monkeypatch.setattr(boost, "acquire_run_lock", lambda name: None)
    monkeypatch.setattr(boost.atexit, "register", lambda f: None)
    monkeypatch.setattr(boost, "_fetch_targets", lambda c, sid: ([], False))

    def fake_resolve(api_key, sid):  # type: ignore[no-untyped-def]
        order.append("resolve")
        return "76561197960287930"

    def fake_validate(c):  # type: ignore[no-untyped-def]
        order.append("validate")
        seen["validate_steam_id"] = c.steam_id

    monkeypatch.setattr(boost, "resolve_steam_id", fake_resolve)
    monkeypatch.setattr(boost, "validate", fake_validate)


def test_main_resolves_steam_id_before_validate(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # RA-B: validate шлёт steam_id в GetPlayerSummaries, которому нужен числовой
    # ID64. Значит resolve (vanity/URL → ID64) ОБЯЗАН идти ДО validate, и validate
    # должен видеть уже резолвнутое значение — иначе ложное «API key invalid».
    order: list[str] = []
    seen: dict[str, str] = {}
    _stub_main_deps(monkeypatch, _cfg(steam_id="gabelogannewell"), order, seen)

    with pytest.raises(SystemExit):
        boost.main()

    assert order == ["resolve", "validate"]  # resolve ПЕРЕД validate
    assert seen["validate_steam_id"] == "76561197960287930"


def test_main_empty_steam_id_not_resolved(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Пустой steam_id НЕ резолвим (лишний сетевой вызов) — пусть validate выдаст
    # локальную ошибку «steam_id is missing».
    order: list[str] = []
    seen: dict[str, str] = {}
    _stub_main_deps(monkeypatch, _cfg(steam_id=""), order, seen)

    with pytest.raises(SystemExit):
        boost.main()

    assert "resolve" not in order  # пустой id не резолвится
    assert order == ["validate"]


def test_main_resolve_failure_exits_cleanly(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Сбой резолва (сеть/неуспех vanity) → чистый sys.exit(1), не сырой трейсбек.
    order: list[str] = []
    seen: dict[str, str] = {}
    _stub_main_deps(monkeypatch, _cfg(steam_id="badvanity"), order, seen)

    def boom(api_key, sid):  # type: ignore[no-untyped-def]
        raise RuntimeError("vanity не резолвится")

    monkeypatch.setattr(boost, "resolve_steam_id", boom)

    with pytest.raises(SystemExit) as exc:
        boost.main()

    assert exc.value.code == 1
    assert "validate" not in order  # до validate не дошли
