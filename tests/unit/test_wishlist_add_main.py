"""Тесты оркестрации main() wishlist_add.py — разбор флагов, resolve→validate,
guard --list vs --reset/--retry-errors, wiring в run(). Паттерн загрузки —
как test_add_demos_main.py (scripts/ не пакет). Закрывает пробел покрытия B-2.
"""

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
    / "wishlist_add.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "wishlist_add_under_test_main", _SCRIPT_PATH
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wishlist_add = _load()


def _cfg(**over: object) -> SimpleNamespace:
    base = {
        "steam_api_key": "k",
        "steam_id": "gabelogannewell",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _stub_common(monkeypatch, cfg, argv) -> dict:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(wishlist_add, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(wishlist_add, "load_config", lambda: cfg)
    calls: dict = {"run": None}
    monkeypatch.setattr(
        wishlist_add, "run", lambda **kw: calls.__setitem__("run", kw)
    )
    return calls


# ── resolve → validate (RA-B) ────────────────────────────────────────────


def test_main_resolves_steam_id_before_validate(monkeypatch) -> None:
    order: list[str] = []
    cfg = _cfg(steam_id="gabelogannewell")
    _stub_common(monkeypatch, cfg, ["wishlist_add.py"])

    def fake_resolve(api_key, sid):
        order.append("resolve")
        return "76561197960287930"

    def fake_validate(c):
        order.append("validate")

    monkeypatch.setattr(wishlist_add, "resolve_steam_id", fake_resolve)
    monkeypatch.setattr(wishlist_add, "validate", fake_validate)

    wishlist_add.main()

    assert order == ["resolve", "validate"]
    assert cfg.steam_id == "76561197960287930"


def test_main_empty_steam_id_not_resolved(monkeypatch) -> None:
    order: list[str] = []
    cfg = _cfg(steam_id="")
    _stub_common(monkeypatch, cfg, ["wishlist_add.py"])

    monkeypatch.setattr(
        wishlist_add,
        "resolve_steam_id",
        lambda *a: (_ for _ in ()).throw(
            AssertionError("пустой id не должен резолвиться")
        ),
    )
    monkeypatch.setattr(
        wishlist_add, "validate", lambda c: order.append("validate")
    )

    wishlist_add.main()

    assert order == ["validate"]


def test_main_resolve_failure_exits_cleanly(monkeypatch) -> None:
    cfg = _cfg(steam_id="badvanity")
    _stub_common(monkeypatch, cfg, ["wishlist_add.py"])

    def boom(api_key, sid):
        raise RuntimeError("vanity не резолвится")

    monkeypatch.setattr(wishlist_add, "resolve_steam_id", boom)
    monkeypatch.setattr(
        wishlist_add,
        "validate",
        lambda c: (_ for _ in ()).throw(
            AssertionError("до validate не должны дойти")
        ),
    )

    with pytest.raises(SystemExit) as exc:
        wishlist_add.main()

    assert exc.value.code == 1


# ── --list vs --reset/--retry-errors guard ──────────────────────────────


def test_main_list_with_reset_warns_and_ignores_reset(monkeypatch) -> None:
    cfg = _cfg()
    calls = _stub_common(
        monkeypatch, cfg, ["wishlist_add.py", "--list", "--reset"]
    )
    monkeypatch.setattr(
        wishlist_add, "resolve_steam_id", lambda *a: cfg.steam_id
    )
    monkeypatch.setattr(wishlist_add, "validate", lambda c: None)

    def _boom():
        raise AssertionError("--list не должен чистить state")

    monkeypatch.setattr(wishlist_add.wishlist_state, "clear_state", _boom)

    wishlist_add.main()

    assert calls["run"]["list_only"] is True


def test_main_reset_clears_state_before_run(monkeypatch) -> None:
    cfg = _cfg()
    calls = _stub_common(monkeypatch, cfg, ["wishlist_add.py", "--reset"])
    monkeypatch.setattr(
        wishlist_add, "resolve_steam_id", lambda *a: cfg.steam_id
    )
    monkeypatch.setattr(wishlist_add, "validate", lambda c: None)

    cleared = {"state": False}
    monkeypatch.setattr(
        wishlist_add.wishlist_state,
        "clear_state",
        lambda: cleared.__setitem__("state", True),
    )

    wishlist_add.main()

    assert cleared["state"] is True
    assert calls["run"] is not None


def test_main_retry_errors_clears_only_error_ids(monkeypatch) -> None:
    cfg = _cfg()
    calls = _stub_common(
        monkeypatch, cfg, ["wishlist_add.py", "--retry-errors"]
    )
    monkeypatch.setattr(
        wishlist_add, "resolve_steam_id", lambda *a: cfg.steam_id
    )
    monkeypatch.setattr(wishlist_add, "validate", lambda c: None)

    cleared = {"errors": False}
    monkeypatch.setattr(
        wishlist_add.wishlist_state,
        "clear_error_ids",
        lambda: cleared.__setitem__("errors", True),
    )

    wishlist_add.main()

    assert cleared["errors"] is True
    assert calls["run"] is not None


# ── wiring в run() ───────────────────────────────────────────────────────


def test_main_wires_add_and_limit_into_run(monkeypatch) -> None:
    cfg = _cfg()
    calls = _stub_common(
        monkeypatch, cfg, ["wishlist_add.py", "--add", "--limit", "50"]
    )
    monkeypatch.setattr(
        wishlist_add, "resolve_steam_id", lambda *a: cfg.steam_id
    )
    monkeypatch.setattr(wishlist_add, "validate", lambda c: None)

    wishlist_add.main()

    assert calls["run"]["do_add"] is True
    assert calls["run"]["list_only"] is False
    assert calls["run"]["limit"] == 50


def test_main_wires_interval_and_resolved_steam_id_into_run(
    monkeypatch,
) -> None:
    # run() вишлиста получает steam_id/api_key отдельно (GetWishlist,
    # GetOwnedGames) — туда должен уйти уже резолвнутый ID64, а не vanity.
    cfg = _cfg(steam_id="gabelogannewell")
    calls = _stub_common(
        monkeypatch, cfg, ["wishlist_add.py", "--add", "--interval", "0"]
    )
    monkeypatch.setattr(
        wishlist_add, "resolve_steam_id", lambda *a: "76561197960287930"
    )
    monkeypatch.setattr(wishlist_add, "validate", lambda c: None)

    wishlist_add.main()

    assert calls["run"]["interval"] == 0.0
    assert calls["run"]["steam_id"] == "76561197960287930"
    assert calls["run"]["api_key"] == "k"


def test_main_interval_defaults_to_one_second(monkeypatch) -> None:
    cfg = _cfg()
    calls = _stub_common(monkeypatch, cfg, ["wishlist_add.py"])
    monkeypatch.setattr(
        wishlist_add, "resolve_steam_id", lambda *a: cfg.steam_id
    )
    monkeypatch.setattr(wishlist_add, "validate", lambda c: None)

    wishlist_add.main()

    assert calls["run"]["interval"] == 1.0


# ── B-14: флаги типов контента ──────────────────────────────────────────


def _run_with(monkeypatch, *flags: str) -> dict:  # type: ignore[no-untyped-def]
    cfg = _cfg()
    calls = _stub_common(monkeypatch, cfg, ["wishlist_add.py", *flags])
    monkeypatch.setattr(
        wishlist_add, "resolve_steam_id", lambda *a: cfg.steam_id
    )
    monkeypatch.setattr(wishlist_add, "validate", lambda c: None)
    wishlist_add.main()
    return calls["run"]


def test_main_without_type_flags_takes_all_types(monkeypatch) -> None:
    run_kw = _run_with(monkeypatch)
    assert run_kw["types"] == frozenset(
        {"games", "dlc", "demos", "software", "videos", "hardware"}
    )


@pytest.mark.parametrize(
    ("flag", "kind"),
    [
        ("--games", "games"),
        ("--dlc", "dlc"),
        ("--DLC", "dlc"),
        ("--dls", "dlc"),
        ("--DLS", "dlc"),
        ("--demos", "demos"),
        ("--software", "software"),
        ("--videos", "videos"),
        ("--hardware", "hardware"),
    ],
)
def test_main_single_type_flag(monkeypatch, flag, kind) -> None:
    assert _run_with(monkeypatch, flag)["types"] == frozenset({kind})


def test_main_type_flags_combine(monkeypatch) -> None:
    run_kw = _run_with(monkeypatch, "--games", "--demos")
    assert run_kw["types"] == frozenset({"games", "demos"})
