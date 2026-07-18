"""Тесты оркестрации discover/add/run (app/wishlist/orchestrate.py)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import app.wishlist.orchestrate as orch
import app.wishlist.state as state_mod


def _patch_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        state_mod, "CANDIDATES_FILE", tmp_path / "candidates.txt"
    )
    monkeypatch.setattr(state_mod, "ADDED_FILE", tmp_path / "added.txt")
    monkeypatch.setattr(state_mod, "REFUSED_FILE", tmp_path / "refused.txt")
    monkeypatch.setattr(state_mod, "ERROR_FILE", tmp_path / "error.txt")


# ── discover() ────────────────────────────────────────────────────────────


def test_discover_subtracts_added_and_refused(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        orch.discovery, "discover_candidates", lambda **_k: [1, 2, 3, 4, 5]
    )
    state_mod.mark_added(3)
    state_mod.mark_refused(4)

    result = orch.discover(api_key="key", steam_id="76561198190468628")

    assert result == [1, 2, 5]
    assert state_mod.load_candidates() == [1, 2, 5]


def test_discover_passes_api_key_and_steam_id_through(
    monkeypatch, tmp_path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    captured = {}

    def fake_discover_candidates(*, api_key, steam_id):
        captured["api_key"] = api_key
        captured["steam_id"] = steam_id
        return []

    monkeypatch.setattr(
        orch.discovery, "discover_candidates", fake_discover_candidates
    )
    orch.discover(api_key="mykey", steam_id="76561198190468628")
    assert captured == {"api_key": "mykey", "steam_id": "76561198190468628"}


def test_discover_failure_propagates_without_overwriting_candidates(
    monkeypatch, tmp_path
) -> None:
    # Живая находка 2026-07-19: transient GetAppList-сбой не должен затирать
    # уже сохранённый candidates.txt пустым списком — discovery.discover_candidates
    # теперь пробрасывает исключение (не глотает в []), и discover() должно
    # упасть ДО вызова state.save_candidates().
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([100, 200, 300])

    def _boom(**_k):
        raise RuntimeError("Steam API вернул 500")

    monkeypatch.setattr(orch.discovery, "discover_candidates", _boom)

    with pytest.raises(RuntimeError, match="Steam API вернул 500"):
        orch.discover(api_key="key", steam_id="76561198190468628")

    assert state_mod.load_candidates() == [100, 200, 300]


# ── add() ─────────────────────────────────────────────────────────────────


def test_add_skips_already_processed_ids(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3, 4])
    state_mod.mark_added(1)
    state_mod.mark_refused(2)
    state_mod.mark_error(3)

    captured = {}

    def fake_add_pending(access_token, appids, **_k):
        captured["appids"] = appids
        return orch.wishlist_api.AddResult(added=list(appids))

    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)
    monkeypatch.setattr(
        orch,
        "get_web_cookies",
        lambda *_a, **_k: {"steamLoginSecure": "76561198190468628||jwt.tok"},
    )

    result = orch.add()

    assert captured["appids"] == [4]
    assert result.added == [4]
    assert state_mod.load_added_ids() == {1, 4}


def test_add_respects_limit(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3])
    captured = {}

    def fake_add_pending(access_token, appids, **_k):
        captured["appids"] = appids
        return orch.wishlist_api.AddResult(added=list(appids))

    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)
    monkeypatch.setattr(
        orch,
        "get_web_cookies",
        lambda *_a, **_k: {"steamLoginSecure": "id||jwt"},
    )

    orch.add(limit=2)

    assert captured["appids"] == [1, 2]


def test_add_no_pending_returns_empty_without_cookie_fetch(
    monkeypatch, tmp_path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1])
    state_mod.mark_added(1)

    def _boom(*_a, **_k):
        raise AssertionError(
            "get_web_cookies не должен вызываться без кандидатов"
        )

    monkeypatch.setattr(orch, "get_web_cookies", _boom)

    result = orch.add()

    assert result == orch.wishlist_api.AddResult()


def test_add_no_session_returns_auth_fail_without_marking_error(
    monkeypatch, tmp_path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])
    monkeypatch.setattr(orch, "get_web_cookies", lambda *_a, **_k: None)

    result = orch.add()

    assert result.auth_fail is True
    assert (
        state_mod.load_error_ids() == set()
    )  # НЕ error.txt — resume подхватит


def test_add_passes_access_token_extracted_from_cookie(
    monkeypatch, tmp_path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1])
    captured = {}

    def fake_add_pending(access_token, appids, **_k):
        captured["access_token"] = access_token
        return orch.wishlist_api.AddResult(added=list(appids))

    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)
    monkeypatch.setattr(
        orch,
        "get_web_cookies",
        lambda *_a, **_k: {
            "steamLoginSecure": "76561198190468628||the.jwt.token"
        },
    )

    orch.add()

    assert captured["access_token"] == "the.jwt.token"


def test_add_auth_fail_retries_once_with_fresh_cookie(
    monkeypatch, tmp_path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])
    cookies_calls = {"n": 0}

    def fake_get_web_cookies(*_a, **_k):
        cookies_calls["n"] += 1
        return {"steamLoginSecure": f"id||tok{cookies_calls['n']}"}

    monkeypatch.setattr(orch, "get_web_cookies", fake_get_web_cookies)

    add_calls = {"n": 0}

    def fake_add_pending(access_token, appids, **_k):
        add_calls["n"] += 1
        if add_calls["n"] == 1:
            return orch.wishlist_api.AddResult(auth_fail=True)
        return orch.wishlist_api.AddResult(added=list(appids))

    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)

    result = orch.add()

    assert cookies_calls["n"] == 2  # первичный + одна попытка обновления
    assert result.added == [1, 2]
    assert result.auth_fail is False


def test_add_auth_fail_retry_also_fails_leaves_pending_unmarked(
    monkeypatch, tmp_path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])
    cookies_calls = {"n": 0}

    def fake_get_web_cookies(*_a, **_k):
        cookies_calls["n"] += 1
        if cookies_calls["n"] == 1:
            return {"steamLoginSecure": "id||tok1"}
        return None  # обновление тоже не удалось

    monkeypatch.setattr(orch, "get_web_cookies", fake_get_web_cookies)
    monkeypatch.setattr(
        orch.wishlist_api,
        "add_pending",
        lambda *_a, **_k: orch.wishlist_api.AddResult(auth_fail=True),
    )

    result = orch.add()

    assert result.auth_fail is True
    assert state_mod.load_added_ids() == set()
    assert state_mod.load_error_ids() == set()


def test_add_auth_fail_retry_merges_partial_results(
    monkeypatch, tmp_path
) -> None:
    """Проверяет, что результаты первой и retry-попытки сливаются (не заменяются).

    Первая попытка добавляет appid=1 но потом получает auth_fail. Retry добавляет
    appid=2,3. Финальный result должен содержать ВСЕ три [1,2,3], а не только
    результат retry.
    """
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3])

    def fake_get_web_cookies(*_a, **_k):
        return {"steamLoginSecure": "id||freshtoken"}

    add_calls = {"n": 0}

    def fake_add_pending(access_token, appids, **_k):
        add_calls["n"] += 1
        if add_calls["n"] == 1:
            # Первая попытка: добавлено appid=1, потом auth_fail
            # remaining будет [2,3]
            return orch.wishlist_api.AddResult(
                added=[1], refused=[], error=[], auth_fail=True, hit_wall=False
            )
        # Retry: добавлено [2,3]
        return orch.wishlist_api.AddResult(
            added=list(appids),
            refused=[],
            error=[],
            auth_fail=False,
            hit_wall=False,
        )

    monkeypatch.setattr(orch, "get_web_cookies", fake_get_web_cookies)
    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)

    result = orch.add()

    # Финальный result должен содержать все три: [1, 2, 3]
    assert sorted(result.added) == [1, 2, 3]
    assert result.refused == []
    assert result.auth_fail is False


def test_add_auth_fail_retry_merges_hit_wall_with_or_logic(
    monkeypatch, tmp_path
) -> None:
    """hit_wall должно слиться с OR: если первая попытка hit_wall=True, финальный
    результат тоже hit_wall=True, даже если retry не вернул hit_wall.
    """
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3])

    def fake_get_web_cookies(*_a, **_k):
        return {"steamLoginSecure": "id||freshtoken"}

    add_calls = {"n": 0}

    def fake_add_pending(access_token, appids, **_k):
        add_calls["n"] += 1
        if add_calls["n"] == 1:
            # Первая попытка: hit_wall=True и auth_fail=True
            return orch.wishlist_api.AddResult(
                added=[1],
                refused=[],
                error=[],
                auth_fail=True,
                hit_wall=True,
            )
        # Retry: добавилось ещё, но hit_wall=False
        return orch.wishlist_api.AddResult(
            added=[2, 3], refused=[], error=[], auth_fail=False, hit_wall=False
        )

    monkeypatch.setattr(orch, "get_web_cookies", fake_get_web_cookies)
    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)

    result = orch.add()

    # hit_wall должно остаться True (OR логика: True | False = True)
    assert result.hit_wall is True
    assert sorted(result.added) == [1, 2, 3]
    assert result.auth_fail is False


def test_add_auth_fail_retry_excludes_error_appids(
    monkeypatch, tmp_path
) -> None:
    """Appid из result.error должен быть исключён из remaining и не ретраиться.

    Первая попытка: appid=1 добавлено, appid=2 словил ошибку (error),
    appid=3 нет в результате (ещё не обработана). Потом auth_fail. Retry
    должен получить только [3], а не [2,3]. Финально: added не содержит 2,
    error содержит 2, пересечение пусто.
    """
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3])

    def fake_get_web_cookies(*_a, **_k):
        return {"steamLoginSecure": "id||freshtoken"}

    add_calls = {"n": 0}

    def fake_add_pending(access_token, appids, **_k):
        add_calls["n"] += 1
        if add_calls["n"] == 1:
            # Первая попытка: appid=1 успех, appid=2 ошибка, потом auth_fail
            return orch.wishlist_api.AddResult(
                added=[1],
                refused=[],
                error=[2],
                auth_fail=True,
                hit_wall=False,
            )
        # Retry должен получить только [3], успешно добавляет его
        # Проверяем, что 2 не передан (исключён из remaining)
        assert 2 not in appids, (
            f"appid=2 из error должен быть исключён, но передан: {appids}"
        )
        return orch.wishlist_api.AddResult(
            added=list(appids),
            refused=[],
            error=[],
            auth_fail=False,
            hit_wall=False,
        )

    monkeypatch.setattr(orch, "get_web_cookies", fake_get_web_cookies)
    monkeypatch.setattr(orch.wishlist_api, "add_pending", fake_add_pending)

    result = orch.add()

    # Финально: [1, 3] в added, [2] в error, пересечение пустое
    assert sorted(result.added) == [1, 3]
    assert result.error == [2]
    # Главное: added и error не должны пересекаться (no double-accounting)
    assert not (set(result.added) & set(result.error))
    assert result.auth_fail is False


# ── run() ─────────────────────────────────────────────────────────────────


def test_run_list_only_does_not_call_discover(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])

    def _boom(**_k):
        raise AssertionError("discover не должен вызываться при --list")

    monkeypatch.setattr(orch, "discover", _boom)

    orch.run(
        do_add=False,
        list_only=True,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )


def test_run_dry_run_reports_without_adding(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2, 3])
    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    def _boom(**_k):
        raise AssertionError("add не должен вызываться без --add")

    monkeypatch.setattr(orch, "add", _boom)

    orch.run(
        do_add=False,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "dry_run"
    assert captured["added"] == 3


def test_run_add_reports_ok(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])
    monkeypatch.setattr(
        orch, "add", lambda **_k: orch.wishlist_api.AddResult(added=[1, 2])
    )
    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "ok"
    assert captured["added"] == 2
    assert captured["hit_wall"] is False


def test_run_add_hit_wall_reports_not_ok(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])
    monkeypatch.setattr(
        orch,
        "add",
        lambda **_k: orch.wishlist_api.AddResult(added=[1], hit_wall=True),
    )
    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "ok"
    assert captured["hit_wall"] is True  # report_result сам решает ✅/⚠️


def test_run_add_auth_fail_reports_error(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])
    monkeypatch.setattr(
        orch, "add", lambda **_k: orch.wishlist_api.AddResult(auth_fail=True)
    )
    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "error"


def test_run_add_exception_reports_error(monkeypatch, tmp_path) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])

    def _boom(**_k):
        raise RuntimeError("сеть упала")

    monkeypatch.setattr(orch, "add", _boom)
    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "error"


def test_run_add_keyboard_interrupt_reports_interrupted(
    monkeypatch, tmp_path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])

    def _boom(**_k):
        raise KeyboardInterrupt()

    monkeypatch.setattr(orch, "add", _boom)
    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "interrupted"


def test_run_dry_run_discover_exception_reports_error(
    monkeypatch, tmp_path
) -> None:
    _patch_state(monkeypatch, tmp_path)

    def _boom(**_k):
        raise RuntimeError("сеть упала")

    monkeypatch.setattr(orch, "discover", _boom)
    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    orch.run(
        do_add=False,
        list_only=False,
        limit=None,
        interval=1.0,
        api_key="k",
        steam_id="s",
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "error"
