"""Тесты отбора игр для boost из all.txt (режим «все игры»)."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace

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


def test_select_targets_filters_and_builds() -> None:
    out = boost._select_targets(
        all_ids=[10, 20, 30, 40, 50],
        played={10: 5, 20: 0, 30: 100},
        skip={40},
        target=3,
        names={20: "Game20"},
    )
    # 10/30 уже >= target, 40 в skip — отброшены; 20 и неизвестная 50 остаются
    assert [g["appid"] for g in out] == [20, 50]


def test_select_targets_builds_dicts_with_name_fallback() -> None:
    out = boost._select_targets(
        all_ids=[20, 50],
        played={20: 1},
        skip=set(),
        target=3,
        names={20: "Game20"},
    )
    # 20 есть в Steam API (known=True), 50 — нет (known=False)
    assert out[0] == {
        "appid": 20,
        "name": "Game20",
        "playtime_forever": 1,
        "known": True,
    }
    # неизвестная игра: playtime 0, имя = строка appid, known=False
    assert out[1] == {
        "appid": 50,
        "name": "50",
        "playtime_forever": 0,
        "known": False,
    }


def test_select_targets_preserves_order() -> None:
    out = boost._select_targets(
        all_ids=[30, 10, 20],
        played={},
        skip=set(),
        target=3,
        names={},
    )
    assert [g["appid"] for g in out] == [30, 10, 20]


# ── CLI: --reset ────────────────────────────────────────────────────────────


def test_parser_reset() -> None:
    assert boost._build_parser().parse_args(["--reset"]).reset


def test_parser_defaults_no_reset() -> None:
    assert not boost._build_parser().parse_args([]).reset


def test_prepare_progress_reset_clears(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    called: list[str] = []
    monkeypatch.setattr(
        boost, "clear_playtime_progress", lambda: called.append("x")
    )
    boost._prepare_progress(boost._build_parser().parse_args(["--reset"]))
    assert called == ["x"]


def test_prepare_progress_noop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    called: list[str] = []
    monkeypatch.setattr(
        boost, "clear_playtime_progress", lambda: called.append("x")
    )
    monkeypatch.setattr(
        boost, "clear_playtime_skip", lambda: called.append("s")
    )
    boost._prepare_progress(boost._build_parser().parse_args([]))
    assert called == []


def test_parser_retry_skips() -> None:
    assert boost._build_parser().parse_args(["--retry-skips"]).retry_skips


# ── M2: пустой owned-games API ──────────────────────────────────────────────


def _patch_fetch_deps(monkeypatch, owned: list[dict]) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(boost, "read_ids_ordered", lambda p: [1, 2, 3])
    monkeypatch.setattr(boost, "fetch_owned_games", lambda k, s: owned)
    monkeypatch.setattr(boost, "load_playtime_skip_ids", set)
    monkeypatch.setattr(boost, "load_playtime_done_ids", set)
    monkeypatch.setattr(boost, "load_game_names", dict)


def test_fetch_targets_warns_when_owned_empty(monkeypatch, caplog) -> None:  # type: ignore[no-untyped-def]
    _patch_fetch_deps(monkeypatch, owned=[])
    cfg = SimpleNamespace(
        steam_api_key="k", exclude_ids=[], playtime_target_minutes=3
    )
    with caplog.at_level(logging.WARNING, logger="sam_automation"):
        out = boost._fetch_targets(cfg, "sid")
    # предупредил про owned, но НЕ абортил — цели всё равно собраны
    assert any("owned" in r.message.lower() for r in caplog.records)
    assert [g["appid"] for g in out] == [1, 2, 3]


def test_fetch_targets_no_warn_when_owned_present(monkeypatch, caplog) -> None:  # type: ignore[no-untyped-def]
    _patch_fetch_deps(monkeypatch, owned=[{"appid": 1, "playtime_forever": 0}])
    cfg = SimpleNamespace(
        steam_api_key="k", exclude_ids=[], playtime_target_minutes=3
    )
    with caplog.at_level(logging.WARNING, logger="sam_automation"):
        boost._fetch_targets(cfg, "sid")
    assert not any("owned" in r.message.lower() for r in caplog.records)


def test_prepare_progress_retry_skips_clears(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    called: list[str] = []
    monkeypatch.setattr(boost, "clear_playtime_progress", lambda: None)
    monkeypatch.setattr(
        boost, "clear_playtime_skip", lambda: called.append("s")
    )
    boost._prepare_progress(boost._build_parser().parse_args(["--retry-skips"]))
    assert called == ["s"]
