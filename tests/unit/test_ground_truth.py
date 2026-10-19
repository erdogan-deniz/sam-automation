"""Тесты scripts/verify/verify_state.py — сверка bookkeeping с реальным Steam.

Слепая зона full-project-аудита 2026-08-10 (#5): ничего не сверяло
added.txt/refused.txt с реальным состоянием на стороне Steam — весь аудит
проверял только внутреннюю самосогласованность bookkeeping. v1 — free_games
(GetOwnedGames) и wishlist (GetWishlist), оба дают весь список ОДНИМ вызовом.
Внешние источники (fetch_owned_games/fetch_wishlist_ids) и state-модули
замоканы — читается только поведение diff/main().
"""

from __future__ import annotations

import pytest

import scripts.verify.verify_state as gt
from app.config import Config

_STEAM_ID = "76561197960287930"


def _setup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gt, "setup_logging", lambda **k: None)
    monkeypatch.setattr(
        gt,
        "load_config",
        lambda: Config(steam_api_key="key", steam_id=_STEAM_ID),
    )
    monkeypatch.setattr(gt, "validate", lambda cfg: None)
    monkeypatch.setattr(gt, "resolve_steam_id", lambda key, sid: sid)


# ── _check_free_games ────────────────────────────────────────────────────


def test_check_free_games_no_added_skips_api_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gt.free_games_state, "load_added_ids", lambda: set())

    def _boom(api_key, steam_id):
        raise AssertionError("не должен звать API без added.txt")

    monkeypatch.setattr(gt, "fetch_owned_games", _boom)

    assert gt._check_free_games("key", _STEAM_ID) == []


def test_check_free_games_all_owned_no_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gt.free_games_state, "load_added_ids", lambda: {730, 440}
    )
    monkeypatch.setattr(
        gt,
        "fetch_owned_games",
        lambda api_key, steam_id: [{"appid": 730}, {"appid": 440}],
    )

    assert gt._check_free_games("key", _STEAM_ID) == []


def test_check_free_games_reports_missing_from_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 999 помечен added.txt, но реально НЕ owned — сигнал потерянного
    # персиста (High-баг FG-1: batch-персист терял уже выданные лицензии).
    monkeypatch.setattr(
        gt.free_games_state, "load_added_ids", lambda: {730, 999}
    )
    monkeypatch.setattr(
        gt,
        "fetch_owned_games",
        lambda api_key, steam_id: [{"appid": 730}],
    )

    assert gt._check_free_games("key", _STEAM_ID) == [999]


# ── _check_wishlist ───────────────────────────────────────────────────────


def test_check_wishlist_no_added_skips_api_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gt.wishlist_state, "load_added_ids", lambda: set())

    def _boom(steam_id):
        raise AssertionError("не должен звать API без added.txt")

    monkeypatch.setattr(gt, "fetch_wishlist_ids", _boom)

    assert gt._check_wishlist(_STEAM_ID) == []


def test_check_wishlist_all_present_no_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gt.wishlist_state, "load_added_ids", lambda: {10, 20})
    monkeypatch.setattr(gt, "fetch_wishlist_ids", lambda steam_id: {10, 20})

    assert gt._check_wishlist(_STEAM_ID) == []


def test_check_wishlist_reports_missing_from_live_wishlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gt.wishlist_state, "load_added_ids", lambda: {10, 20})
    monkeypatch.setattr(gt, "fetch_wishlist_ids", lambda steam_id: {10})

    assert gt._check_wishlist(_STEAM_ID) == [20]


# ── _check_demos ─────────────────────────────────────────────────────────


def test_check_demos_no_added_skips_api_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gt.demos_state, "load_added_ids", lambda: set())

    def _boom(api_key, steam_id):
        raise AssertionError("не должен звать API без added.txt")

    monkeypatch.setattr(gt, "fetch_owned_games", _boom)

    assert gt._check_demos("key", _STEAM_ID) == []


def test_check_demos_all_owned_no_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gt.demos_state, "load_added_ids", lambda: {228980})
    monkeypatch.setattr(
        gt,
        "fetch_owned_games",
        lambda api_key, steam_id: [{"appid": 228980}],
    )

    assert gt._check_demos("key", _STEAM_ID) == []


def test_check_demos_reports_missing_from_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gt.demos_state, "load_added_ids", lambda: {228980, 999})
    monkeypatch.setattr(
        gt,
        "fetch_owned_games",
        lambda api_key, steam_id: [{"appid": 228980}],
    )

    assert gt._check_demos("key", _STEAM_ID) == [999]


# ── main() — коды выхода ────────────────────────────────────────────────


def test_main_returns_normally_when_everything_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(monkeypatch)
    monkeypatch.setattr(gt, "_check_free_games", lambda key, sid: [])
    monkeypatch.setattr(gt, "_check_wishlist", lambda sid: [])
    monkeypatch.setattr(gt, "_check_demos", lambda key, sid: [])

    gt.main()  # не должен звать sys.exit вовсе — успешное завершение


def test_main_exits_one_when_free_games_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(monkeypatch)
    monkeypatch.setattr(gt, "_check_free_games", lambda key, sid: [999])
    monkeypatch.setattr(gt, "_check_wishlist", lambda sid: [])
    monkeypatch.setattr(gt, "_check_demos", lambda key, sid: [])

    with pytest.raises(SystemExit) as exc:
        gt.main()
    assert exc.value.code == 1


def test_main_exits_one_when_wishlist_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(monkeypatch)
    monkeypatch.setattr(gt, "_check_free_games", lambda key, sid: [])
    monkeypatch.setattr(gt, "_check_wishlist", lambda sid: [20])
    monkeypatch.setattr(gt, "_check_demos", lambda key, sid: [])

    with pytest.raises(SystemExit) as exc:
        gt.main()
    assert exc.value.code == 1


def _boom_runtime(*_a: object) -> list[int]:
    raise RuntimeError("Steam API: game_count=5, но список games пуст")


def test_main_failed_check_exits_two_and_still_runs_others(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # B-6: сбой Steam API в одной проверке — это «не удалось проверить», а не
    # сырой traceback и не «всё в порядке». Остальные проверки отрабатывают.
    _setup(monkeypatch)
    ran: list[str] = []
    monkeypatch.setattr(gt, "_check_free_games", _boom_runtime)
    monkeypatch.setattr(
        gt, "_check_wishlist", lambda sid: ran.append("wishlist") or []
    )
    monkeypatch.setattr(
        gt, "_check_demos", lambda key, sid: ran.append("demos") or []
    )

    with (
        caplog.at_level("INFO", logger="sam_automation"),
        pytest.raises(SystemExit) as exc,
    ):
        gt.main()

    assert exc.value.code == 2
    assert ran == ["wishlist", "demos"]
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "соответствует Steam" not in logged
    assert "НЕ ЗАВЕРШЕНА" in logged


def test_main_mismatch_wins_over_failed_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Найденное расхождение важнее «не удалось проверить» — код 1.
    _setup(monkeypatch)
    monkeypatch.setattr(gt, "_check_free_games", _boom_runtime)
    monkeypatch.setattr(gt, "_check_wishlist", lambda sid: [20])
    monkeypatch.setattr(gt, "_check_demos", lambda key, sid: [])

    with pytest.raises(SystemExit) as exc:
        gt.main()
    assert exc.value.code == 1


def test_main_exits_one_when_demos_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _setup(monkeypatch)
    monkeypatch.setattr(gt, "_check_free_games", lambda key, sid: [])
    monkeypatch.setattr(gt, "_check_wishlist", lambda sid: [])
    monkeypatch.setattr(gt, "_check_demos", lambda key, sid: [228980])

    with pytest.raises(SystemExit) as exc:
        gt.main()
    assert exc.value.code == 1
