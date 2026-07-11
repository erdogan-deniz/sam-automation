"""Тесты CLI-флага --reset скрипта scripts/cards/farm.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_FARM_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "cards" / "farm.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "cards_farm_under_test", _FARM_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


farm = _load()


def test_parser_defaults_no_reset() -> None:
    assert not farm._build_parser().parse_args([]).reset


def test_parser_reset() -> None:
    assert farm._build_parser().parse_args(["--reset"]).reset


def test_prepare_progress_reset_clears_cards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        farm, "clear_card_progress", lambda: called.append("cards")
    )
    farm._prepare_progress(farm._build_parser().parse_args(["--reset"]))
    assert called == ["cards"]


def test_prepare_progress_noop_without_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        farm, "clear_card_progress", lambda: called.append("cards")
    )
    farm._prepare_progress(farm._build_parser().parse_args([]))
    assert called == []
