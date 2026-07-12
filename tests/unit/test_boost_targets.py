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
        done=set(),
        target=3,
        names={20: "Game20"},
    )
    # 10/30 уже >= target, 40 в skip — отброшены; 20 и неизвестная 50 остаются
    assert [g["appid"] for g in out] == [20, 50]


def test_select_targets_known_under_target_not_silenced_by_done() -> None:
    # RA-A: done.txt НЕ глушит now-known игру под таргетом (переход
    # unknown→known / самоисцеление после транзиентно-пустого owned).
    out = boost._select_targets(
        all_ids=[10],
        played={10: 1},
        skip=set(),
        done={10},
        target=3,
        names={},
    )
    assert [g["appid"] for g in out] == [10]  # пере-нацелена, не заглушена
    assert out[0]["known"] is True


def test_select_targets_unknown_in_done_is_silenced() -> None:
    # unknown-игра в done.txt остаётся пропущенной (resume — уже набивали вслепую).
    out = boost._select_targets(
        all_ids=[50],
        played={},
        skip=set(),
        done={50},
        target=3,
        names={},
    )
    assert out == []


def test_select_targets_hard_skip_applies_even_to_known() -> None:
    # exclude_ids/skip.txt (hard skip) глушит даже known-под-таргетом.
    out = boost._select_targets(
        all_ids=[10],
        played={10: 0},
        skip={10},
        done=set(),
        target=3,
        names={},
    )
    assert out == []


def test_select_targets_builds_dicts_with_name_fallback() -> None:
    out = boost._select_targets(
        all_ids=[20, 50],
        played={20: 1},
        skip=set(),
        done=set(),
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
        done=set(),
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
        games, blind = boost._fetch_targets(cfg, "sid")
    # предупредил про owned, но НЕ абортил — цели всё равно собраны
    assert any("owned" in r.message.lower() for r in caplog.records)
    assert [g["appid"] for g in games] == [1, 2, 3]


def test_fetch_targets_no_warn_when_owned_present(monkeypatch, caplog) -> None:  # type: ignore[no-untyped-def]
    _patch_fetch_deps(monkeypatch, owned=[{"appid": 1, "playtime_forever": 0}])
    cfg = SimpleNamespace(
        steam_api_key="k", exclude_ids=[], playtime_target_minutes=3
    )
    with caplog.at_level(logging.WARNING, logger="sam_automation"):
        boost._fetch_targets(cfg, "sid")
    assert not any("owned" in r.message.lower() for r in caplog.records)


def test_fetch_targets_returns_blind_true_when_owned_empty(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # RA-A: пустой owned → blind=True (не персистить done — прогон слепой).
    _patch_fetch_deps(monkeypatch, owned=[])
    cfg = SimpleNamespace(
        steam_api_key="k", exclude_ids=[], playtime_target_minutes=3
    )
    _games, blind = boost._fetch_targets(cfg, "sid")
    assert blind is True


def test_fetch_targets_returns_blind_false_when_owned_present(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    _patch_fetch_deps(monkeypatch, owned=[{"appid": 1, "playtime_forever": 0}])
    cfg = SimpleNamespace(
        steam_api_key="k", exclude_ids=[], playtime_target_minutes=3
    )
    _games, blind = boost._fetch_targets(cfg, "sid")
    assert blind is False


def test_fetch_targets_present_owned_composition(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # INFO-фикс: пиннит склейку fetch_owned_games→played→_select_targets на
    # НЕнулевом playtime — набитая known-игра отсекается, недобранная остаётся.
    monkeypatch.setattr(boost, "read_ids_ordered", lambda p: [1, 2])
    monkeypatch.setattr(
        boost,
        "fetch_owned_games",
        lambda k, s: [
            {"appid": 1, "playtime_forever": 5},  # >= target → отсечь
            {"appid": 2, "playtime_forever": 1},  # < target → цель, known
        ],
    )
    monkeypatch.setattr(boost, "load_playtime_skip_ids", set)
    monkeypatch.setattr(boost, "load_playtime_done_ids", set)
    monkeypatch.setattr(boost, "load_game_names", dict)
    cfg = SimpleNamespace(
        steam_api_key="k", exclude_ids=[], playtime_target_minutes=3
    )
    games, blind = boost._fetch_targets(cfg, "sid")
    assert blind is False
    assert [g["appid"] for g in games] == [2]
    assert games[0]["known"] is True
    assert games[0]["playtime_forever"] == 1


def test_prepare_progress_retry_skips_clears(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    called: list[str] = []
    monkeypatch.setattr(boost, "clear_playtime_progress", lambda: None)
    monkeypatch.setattr(
        boost, "clear_playtime_skip", lambda: called.append("s")
    )
    boost._prepare_progress(boost._build_parser().parse_args(["--retry-skips"]))
    assert called == ["s"]
