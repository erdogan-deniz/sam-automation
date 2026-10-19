"""Тесты main() wishlist_clean.py: флаги → run()."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "library"
    / "wishlist_clean.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "wishlist_clean_under_test", _SCRIPT_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wishlist_clean = _load()


def _run_with(monkeypatch, *flags: str) -> dict:  # type: ignore[no-untyped-def]
    cfg = SimpleNamespace(steam_api_key="k", steam_id="vanity")
    monkeypatch.setattr(sys, "argv", ["wishlist_clean.py", *flags])
    monkeypatch.setattr(wishlist_clean, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(wishlist_clean, "load_config", lambda: cfg)
    monkeypatch.setattr(
        wishlist_clean, "resolve_steam_id", lambda *a: "76561197960287930"
    )
    monkeypatch.setattr(wishlist_clean, "validate", lambda c: None)
    calls: dict = {}
    monkeypatch.setattr(wishlist_clean, "run", lambda **kw: calls.update(kw))
    wishlist_clean.main()
    return calls


def test_default_is_dry_run_both_reasons(monkeypatch) -> None:
    kw = _run_with(monkeypatch)
    assert kw["do_remove"] is False
    assert kw["reasons"] == frozenset({"free", "unreleased"})
    assert kw["steam_id"] == "76561197960287930"


@pytest.mark.parametrize(
    ("flag", "reason"), [("--free", "free"), ("--unreleased", "unreleased")]
)
def test_reason_flags(monkeypatch, flag, reason) -> None:
    assert _run_with(monkeypatch, flag)["reasons"] == frozenset({reason})


def test_remove_limit_interval_any_case(monkeypatch) -> None:
    kw = _run_with(monkeypatch, "--REMOVE", "--Limit", "3", "--interval=0")
    assert kw["do_remove"] is True
    assert kw["limit"] == 3
    assert kw["interval"] == 0.0


def test_list_flag(monkeypatch) -> None:
    assert _run_with(monkeypatch, "--list")["list_only"] is True
