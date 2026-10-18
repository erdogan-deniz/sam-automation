"""Тесты оркестрации main() add_demos.py — разбор флагов, resolve→validate,
guard --list vs --reset/--retry-errors, wiring в run(). Паттерн загрузки —
как test_boost_main.py (scripts/ не пакет). Закрывает для add_demos.py тот
пробел покрытия, что B-2 фиксирует для add_free.py/wishlist_add.py.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "library" / "add_demos.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "add_demos_under_test_main", _SCRIPT_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


add_demos = _load()


def _cfg(**over: object) -> SimpleNamespace:
    base = {
        "steam_api_key": "k",
        "steam_id": "gabelogannewell",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _stub_common(monkeypatch, cfg, argv) -> dict:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(add_demos, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(add_demos, "load_config", lambda: cfg)
    calls: dict = {"run": None}
    monkeypatch.setattr(
        add_demos, "run", lambda **kw: calls.__setitem__("run", kw)
    )
    return calls


# ── resolve → validate (RA-B) ────────────────────────────────────────────


def test_main_resolves_steam_id_before_validate(monkeypatch) -> None:
    order: list[str] = []
    cfg = _cfg(steam_id="gabelogannewell")
    _stub_common(monkeypatch, cfg, ["add_demos.py"])

    def fake_resolve(api_key, sid):
        order.append("resolve")
        return "76561197960287930"

    def fake_validate(c):
        order.append("validate")

    monkeypatch.setattr(add_demos, "resolve_steam_id", fake_resolve)
    monkeypatch.setattr(add_demos, "validate", fake_validate)

    add_demos.main()

    assert order == ["resolve", "validate"]
    assert cfg.steam_id == "76561197960287930"


def test_main_empty_steam_id_not_resolved(monkeypatch) -> None:
    order: list[str] = []
    cfg = _cfg(steam_id="")
    _stub_common(monkeypatch, cfg, ["add_demos.py"])

    monkeypatch.setattr(
        add_demos,
        "resolve_steam_id",
        lambda *a: (_ for _ in ()).throw(
            AssertionError("пустой id не должен резолвиться")
        ),
    )
    monkeypatch.setattr(
        add_demos, "validate", lambda c: order.append("validate")
    )

    add_demos.main()

    assert order == ["validate"]


def test_main_resolve_failure_exits_cleanly(monkeypatch) -> None:
    cfg = _cfg(steam_id="badvanity")
    _stub_common(monkeypatch, cfg, ["add_demos.py"])

    def boom(api_key, sid):
        raise RuntimeError("vanity не резолвится")

    monkeypatch.setattr(add_demos, "resolve_steam_id", boom)
    monkeypatch.setattr(
        add_demos,
        "validate",
        lambda c: (_ for _ in ()).throw(
            AssertionError("до validate не должны дойти")
        ),
    )

    with pytest.raises(SystemExit) as exc:
        add_demos.main()

    assert exc.value.code == 1


# ── --list vs --reset/--retry-errors guard ──────────────────────────────


def test_main_list_with_reset_warns_and_ignores_reset(monkeypatch) -> None:
    cfg = _cfg()
    calls = _stub_common(
        monkeypatch, cfg, ["add_demos.py", "--list", "--reset"]
    )
    monkeypatch.setattr(add_demos, "resolve_steam_id", lambda *a: cfg.steam_id)
    monkeypatch.setattr(add_demos, "validate", lambda c: None)

    def _boom():
        raise AssertionError("--list не должен чистить state")

    monkeypatch.setattr(add_demos.demos_state, "clear_state", _boom)

    add_demos.main()

    assert calls["run"]["list_only"] is True


def test_main_reset_clears_state_before_run(monkeypatch) -> None:
    cfg = _cfg()
    calls = _stub_common(monkeypatch, cfg, ["add_demos.py", "--reset"])
    monkeypatch.setattr(add_demos, "resolve_steam_id", lambda *a: cfg.steam_id)
    monkeypatch.setattr(add_demos, "validate", lambda c: None)

    cleared = {"state": False}
    monkeypatch.setattr(
        add_demos.demos_state,
        "clear_state",
        lambda: cleared.__setitem__("state", True),
    )

    add_demos.main()

    assert cleared["state"] is True
    assert calls["run"] is not None


def test_main_retry_errors_clears_only_error_ids(monkeypatch) -> None:
    cfg = _cfg()
    calls = _stub_common(monkeypatch, cfg, ["add_demos.py", "--retry-errors"])
    monkeypatch.setattr(add_demos, "resolve_steam_id", lambda *a: cfg.steam_id)
    monkeypatch.setattr(add_demos, "validate", lambda c: None)

    cleared = {"errors": False}
    monkeypatch.setattr(
        add_demos.demos_state,
        "clear_error_ids",
        lambda: cleared.__setitem__("errors", True),
    )

    add_demos.main()

    assert cleared["errors"] is True
    assert calls["run"] is not None


# ── wiring в run() ───────────────────────────────────────────────────────


def test_main_wires_add_and_limit_into_run(monkeypatch) -> None:
    cfg = _cfg()
    calls = _stub_common(
        monkeypatch, cfg, ["add_demos.py", "--add", "--limit", "50"]
    )
    monkeypatch.setattr(add_demos, "resolve_steam_id", lambda *a: cfg.steam_id)
    monkeypatch.setattr(add_demos, "validate", lambda c: None)

    add_demos.main()

    assert calls["run"]["do_add"] is True
    assert calls["run"]["list_only"] is False
    assert calls["run"]["limit"] == 50
    assert "include_demos" not in calls["run"]
