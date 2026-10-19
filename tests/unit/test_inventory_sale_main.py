"""Тесты main() inventory_sale.py: флаги → run()."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "library"
    / "inventory_sale.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "inventory_sale_under_test", _SCRIPT_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


inventory_sale = _load()


def _run_with(monkeypatch, *flags: str) -> dict:  # type: ignore[no-untyped-def]
    cfg = SimpleNamespace(steam_api_key="k", steam_id="vanity")
    monkeypatch.setattr(sys, "argv", ["inventory_sale.py", *flags])
    monkeypatch.setattr(inventory_sale, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(inventory_sale, "load_config", lambda: cfg)
    monkeypatch.setattr(
        inventory_sale, "resolve_steam_id", lambda *a: "76561197960287930"
    )
    monkeypatch.setattr(inventory_sale, "validate", lambda c: None)
    calls: dict = {}
    monkeypatch.setattr(inventory_sale, "run", lambda **kw: calls.update(kw))
    inventory_sale.main()
    return calls


def test_default_is_dry_run(monkeypatch) -> None:
    kw = _run_with(monkeypatch)
    assert kw["do_sell"] is False
    assert kw["do_grind"] is False
    assert kw["list_only"] is False
    assert kw["reset"] is False
    assert kw["limit"] is None
    assert kw["steam_id"] == "76561197960287930"


def test_sell_and_grind_flags_any_case(monkeypatch) -> None:
    kw = _run_with(monkeypatch, "--SELL", "--Grind")
    assert kw["do_sell"] is True
    assert kw["do_grind"] is True


def test_limit_and_interval(monkeypatch) -> None:
    kw = _run_with(monkeypatch, "--sell", "--limit", "5", "--interval=0")
    assert kw["limit"] == 5
    assert kw["interval"] == 0.0


def test_default_interval_is_three_seconds(monkeypatch) -> None:
    assert _run_with(monkeypatch)["interval"] == 3.0


def test_list_and_reset_flags(monkeypatch) -> None:
    assert _run_with(monkeypatch, "--list")["list_only"] is True
    assert _run_with(monkeypatch, "--reset")["reset"] is True
