"""Тесты оркестрации discover/add (app/free_games/orchestrate.py)."""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.free_games.orchestrate as orch
import app.free_games.state as state_mod


def _patch_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        state_mod, "CANDIDATES_FILE", tmp_path / "candidates.txt"
    )
    monkeypatch.setattr(state_mod, "ADDED_FILE", tmp_path / "added.txt")
    monkeypatch.setattr(state_mod, "REFUSED_FILE", tmp_path / "refused.txt")
    monkeypatch.setattr(state_mod, "ERROR_FILE", tmp_path / "error.txt")


class _FakeClient:
    def __init__(self, licenses: dict) -> None:
        self.licenses = licenses


def _fake_cm_session(client):
    @contextlib.contextmanager
    def _cm(*_a, **_k):
        yield client

    return _cm


# ── discover(): owned/added/refused вычитание ───────────────────────────────


def test_discover_subtracts_owned_added_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        orch.discovery, "discover_candidates", lambda **_k: [1, 2, 3, 4, 5]
    )
    monkeypatch.setattr(orch, "find_steam_path", lambda: "C:/steam")
    monkeypatch.setattr(
        orch, "cm_session", _fake_cm_session(_FakeClient({999: object()}))
    )
    monkeypatch.setattr(orch, "expand_packages_to_apps", lambda _p, _pk: [2])

    state_mod.mark_added(3)
    state_mod.mark_refused(4)

    result = orch.discover(include_demos=True)

    assert result == [1, 5]  # 2=owned, 3=added, 4=refused исключены
    assert state_mod.load_candidates() == [1, 5]


def test_discover_no_steam_path_skips_owned_subtraction(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        orch.discovery, "discover_candidates", lambda **_k: [1, 2]
    )
    monkeypatch.setattr(orch, "find_steam_path", lambda: "")

    result = orch.discover(include_demos=True)

    assert result == [1, 2]  # ничего не вычтено — Steam не найден


def test_discover_cm_login_failed_skips_owned_subtraction(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(
        orch.discovery, "discover_candidates", lambda **_k: [1, 2]
    )
    monkeypatch.setattr(orch, "find_steam_path", lambda: "C:/steam")
    monkeypatch.setattr(orch, "cm_session", _fake_cm_session(None))

    result = orch.discover(include_demos=True)

    assert result == [1, 2]  # логин не удался — owned не вычтен, не падаем


# ── add(): resume-skip + limit + cm_session=None ────────────────────────────


def test_add_skips_already_processed_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3, 4])
    state_mod.mark_added(1)
    state_mod.mark_refused(2)
    state_mod.mark_error(3)

    captured = {}

    def fake_add_licenses(client, appids, **_k):
        captured["appids"] = appids
        return orch.licenses.AddResult(added=appids)

    monkeypatch.setattr(orch.licenses, "add_licenses", fake_add_licenses)
    monkeypatch.setattr(orch, "cm_session", _fake_cm_session(_FakeClient({})))

    result = orch.add()

    assert captured["appids"] == [4]  # только 4 не обработан
    assert result.added == [4]
    assert state_mod.load_added_ids() == {1, 4}


def test_add_respects_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2, 3])

    captured = {}

    def fake_add_licenses(client, appids, **_k):
        captured["appids"] = appids
        return orch.licenses.AddResult(added=appids)

    monkeypatch.setattr(orch.licenses, "add_licenses", fake_add_licenses)
    monkeypatch.setattr(orch, "cm_session", _fake_cm_session(_FakeClient({})))

    orch.add(limit=2)

    assert captured["appids"] == [1, 2]


def test_add_no_pending_returns_empty_without_cm_login(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1])
    state_mod.mark_added(1)

    def _boom(*_a, **_k):
        raise AssertionError("cm_session не должен вызываться без кандидатов")

    monkeypatch.setattr(orch, "cm_session", _boom)

    result = orch.add()

    assert result == orch.licenses.AddResult()


def test_add_cm_login_failed_marks_all_pending_as_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])
    monkeypatch.setattr(orch, "cm_session", _fake_cm_session(None))

    result = orch.add()

    assert result.error == [1, 2]
    assert state_mod.load_error_ids() == {1, 2}


# ── run(): dry-run / --add / --list ветвление ────────────────────────────────


def test_run_list_only_does_not_call_discover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    state_mod.save_candidates([1, 2])

    def _boom(**_k):
        raise AssertionError("discover не должен вызываться при --list")

    monkeypatch.setattr(orch, "discover", _boom)

    orch.run(
        do_add=False,
        list_only=True,
        limit=None,
        include_demos=True,
        cfg=SimpleNamespace(),
    )


def test_run_dry_run_reports_without_adding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2, 3])

    captured = {}
    monkeypatch.setattr(
        orch.report,
        "report_result",
        lambda **kw: captured.update(kw),
    )

    def _boom(**_k):
        raise AssertionError("add не должен вызываться без --add")

    monkeypatch.setattr(orch, "add", _boom)

    orch.run(
        do_add=False,
        list_only=False,
        limit=None,
        include_demos=True,
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "dry_run"
    assert captured["added"] == 3


def test_run_add_reports_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_state(monkeypatch, tmp_path)
    monkeypatch.setattr(orch, "discover", lambda **_k: [1, 2])
    monkeypatch.setattr(
        orch,
        "add",
        lambda **_k: orch.licenses.AddResult(added=[1, 2]),
    )

    captured = {}
    monkeypatch.setattr(
        orch.report, "report_result", lambda **kw: captured.update(kw)
    )

    orch.run(
        do_add=True,
        list_only=False,
        limit=None,
        include_demos=True,
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "ok"
    assert captured["added"] == 2


def test_run_add_exception_reports_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
        include_demos=True,
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "error"


def test_run_add_keyboard_interrupt_reports_interrupted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
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
        include_demos=True,
        cfg=SimpleNamespace(),
    )

    assert captured["status"] == "interrupted"
