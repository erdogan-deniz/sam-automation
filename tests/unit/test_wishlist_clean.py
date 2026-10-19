"""Тесты app/wishlist/clean.py: удаление бесплатного и не вышедшего (B-17/B-18)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.wishlist.clean as clean
import app.wishlist.clean_state as cs
import app.wishlist.state as wstate
from app.wishlist.discovery import StoreFlags


def _patch_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cs, "CANDIDATES_FILE", tmp_path / "c.txt")
    monkeypatch.setattr(cs, "REMOVED_FILE", tmp_path / "removed.txt")
    monkeypatch.setattr(wstate, "ADDED_FILE", tmp_path / "added.txt")


def _stub_store(monkeypatch, wishlist, free=(), coming=()) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        clean.discovery, "fetch_wishlist_ids", lambda _sid: set(wishlist)
    )
    monkeypatch.setattr(
        clean.discovery,
        "fetch_store_flags",
        lambda _ids: StoreFlags(free=set(free), coming_soon=set(coming)),
    )


# ── discover ──────────────────────────────────────────────────────────────


def test_discover_both_reasons_by_default(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    _stub_store(monkeypatch, [1, 2, 3, 4], free=[2], coming=[3])

    assert clean.discover(steam_id="s") == [2, 3]
    assert cs.load_candidates() == [2, 3]


@pytest.mark.parametrize(
    ("reasons", "expected"),
    [(frozenset({"free"}), [2]), (frozenset({"unreleased"}), [3])],
)
def test_discover_single_reason(
    monkeypatch, tmp_path, reasons, expected
) -> None:
    _patch_state(monkeypatch, tmp_path)
    _stub_store(monkeypatch, [1, 2, 3], free=[2], coming=[3])
    assert clean.discover(steam_id="s", reasons=reasons) == expected


def test_discover_store_failure_keeps_old_candidates(
    monkeypatch, tmp_path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    cs.save_candidates([9])
    monkeypatch.setattr(clean.discovery, "fetch_wishlist_ids", lambda _s: {1})

    def _boom(_ids):
        raise RuntimeError("GetItems упал")

    monkeypatch.setattr(clean.discovery, "fetch_store_flags", _boom)
    with pytest.raises(RuntimeError):
        clean.discover(steam_id="s")
    assert cs.load_candidates() == [9]


# ── remove ────────────────────────────────────────────────────────────────


def _cookies(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        clean, "get_web_cookies", lambda *a, **k: {"steamLoginSecure": "x||tok"}
    )


def test_remove_persists_and_unmarks_added(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    cs.save_candidates([1, 2, 3])
    cs.mark_removed(3)  # уже удалён прошлым прогоном — пропускается
    wstate.mark_added(1)
    wstate.mark_added(2)
    wstate.mark_added(7)
    _cookies(monkeypatch)
    seen = {}

    def fake_pending(token, pending, *, interval, persist, call):
        seen["token"] = token
        seen["pending"] = list(pending)
        seen["call"] = call
        persist(1, "added")
        persist(2, "refused")
        return clean.wishlist_api.AddResult(added=[1], refused=[2])

    monkeypatch.setattr(clean.wishlist_api, "add_pending", fake_pending)

    result = clean.remove(interval=0)

    assert seen["token"] == "tok"
    assert seen["pending"] == [1, 2]
    assert seen["call"] is clean.wishlist_api.remove_from_wishlist
    assert result.added == [1]
    assert cs.load_removed_ids() == {1, 3}
    # Удалённое выпадает из added.txt вишлиста, отказ — нет.
    assert wstate.load_added_ids() == {2, 7}


def test_remove_respects_limit(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    cs.save_candidates([1, 2, 3])
    _cookies(monkeypatch)
    seen = {}

    def fake_pending(token, pending, **_k):
        seen["pending"] = list(pending)
        return clean.wishlist_api.AddResult()

    monkeypatch.setattr(clean.wishlist_api, "add_pending", fake_pending)
    clean.remove(limit=2, interval=0)
    assert seen["pending"] == [1, 2]


def test_remove_without_session_is_auth_fail(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    cs.save_candidates([1])
    monkeypatch.setattr(clean, "get_web_cookies", lambda *a, **k: None)
    assert clean.remove(interval=0).auth_fail is True


def test_remove_nothing_pending_skips_session(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)

    def _boom(*a, **k):
        raise AssertionError("без кандидатов сессия не нужна")

    monkeypatch.setattr(clean, "get_web_cookies", _boom)
    assert clean.remove(interval=0).added == []


# ── run ───────────────────────────────────────────────────────────────────


def test_run_dry_run_reports_without_removing(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(clean, "discover", lambda **_k: [1, 2])

    def _boom(**_k):
        raise AssertionError("без --remove удалять нельзя")

    monkeypatch.setattr(clean, "remove", _boom)
    captured = {}
    monkeypatch.setattr(
        clean.report, "report_result", lambda **kw: captured.update(kw)
    )

    clean.run(
        do_remove=False,
        list_only=False,
        limit=None,
        interval=1.0,
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "dry_run"
    assert captured["added"] == 2


def test_run_remove_passes_reasons_and_reports(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    seen = {}
    monkeypatch.setattr(
        clean,
        "discover",
        lambda **kw: seen.setdefault("reasons", kw["reasons"]),
    )
    monkeypatch.setattr(
        clean,
        "remove",
        lambda **_k: clean.wishlist_api.AddResult(added=[1, 2]),
    )
    captured = {}
    monkeypatch.setattr(
        clean.report, "report_result", lambda **kw: captured.update(kw)
    )

    clean.run(
        do_remove=True,
        list_only=False,
        limit=None,
        interval=1.0,
        steam_id="s",
        cfg=SimpleNamespace(),
        reasons=frozenset({"free"}),
    )

    assert seen["reasons"] == frozenset({"free"})
    assert captured["status"] == "ok"
    assert captured["added"] == 2


def test_run_list_only_prints_candidates(monkeypatch, tmp_path, capsys) -> None:
    _patch_state(monkeypatch, tmp_path)
    cs.save_candidates([4, 5])

    def _boom(**_k):
        raise AssertionError("--list не обращается к Steam")

    monkeypatch.setattr(clean, "discover", _boom)
    clean.run(
        do_remove=False,
        list_only=True,
        limit=None,
        interval=1.0,
        steam_id="s",
        cfg=SimpleNamespace(),
    )
    assert capsys.readouterr().out.split() == ["4", "5"]


def test_run_discover_error_reports_error(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)

    def _boom(**_k):
        raise RuntimeError("Steam лёг")

    monkeypatch.setattr(clean, "discover", _boom)
    captured = {}
    monkeypatch.setattr(
        clean.report, "report_result", lambda **kw: captured.update(kw)
    )
    clean.run(
        do_remove=True,
        list_only=False,
        limit=None,
        interval=1.0,
        steam_id="s",
        cfg=SimpleNamespace(),
    )
    assert captured["status"] == "error"
