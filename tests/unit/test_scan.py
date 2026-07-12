"""Тесты scripts/scan.py — оркестрация слияния источников ID → all.txt.

Источники (_read_vdf_ids/_read_api_ids/_read_cm_ids) и внешние зависимости
замоканы: проверяется поведение main() — слияние с дедупом, атомарная запись,
floor-guard против усадки библиотеки при транзиентном отказе источника.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.steam
import scripts.scan as scan
from app.config import Config

_STEAM_ID = "76561197960287930"


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    vdf: list[int],
    api: list[int],
    cm: list[int],
    all_txt: str | None = None,
) -> Path:
    """Патчит источники и внешние зависимости scan; возвращает путь all.txt."""
    all_path = tmp_path / "all.txt"
    if all_txt is not None:
        all_path.write_text(all_txt, encoding="utf-8")

    # scan делает `from app.cache import ALL_IDS_FILE` — патчим именно
    # биндинг в scan (тот же объект читается и для prev_ids, и для записи).
    monkeypatch.setattr(scan, "ALL_IDS_FILE", all_path)
    monkeypatch.setattr(scan, "setup_logging", lambda **k: None)
    monkeypatch.setattr(
        scan,
        "load_config",
        lambda: Config(steam_api_key="key", steam_id=_STEAM_ID),
    )
    monkeypatch.setattr(scan, "validate", lambda cfg: None)
    monkeypatch.setattr(scan, "find_steam_path", lambda: "")
    monkeypatch.setattr(scan, "resolve_steam_id", lambda key, sid: sid)
    monkeypatch.setattr(scan, "_read_vdf_ids", lambda p, sid: list(vdf))
    monkeypatch.setattr(scan, "_read_api_ids", lambda key, sid: list(api))
    monkeypatch.setattr(scan, "_read_cm_ids", lambda p: list(cm))
    return all_path


# ── (a) слияние + дедуп + числовая сортировка на диске ──────────────────────


def test_merge_dedup_writes_numeric_sorted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    all_path = _setup(
        monkeypatch, tmp_path, vdf=[10, 730], api=[730, 440], cm=[440, 999]
    )
    scan.main()
    assert all_path.read_text(encoding="utf-8") == "10\n440\n730\n999\n"


# ── (b) floor-guard против усадки ──────────────────────────────────────────


def test_floor_guard_blocks_suspicious_shrink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prev = "\n".join(str(i) for i in range(1, 101)) + "\n"  # 100 ID
    all_path = _setup(
        monkeypatch, tmp_path, vdf=[1], api=[], cm=[], all_txt=prev
    )
    with pytest.raises(SystemExit) as exc:
        scan.main(allow_shrink=False)
    assert exc.value.code == 1
    # all.txt НЕ перезаписан — всё ещё 100 строк.
    lines = all_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 100


def test_allow_shrink_overrides_floor_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prev = "\n".join(str(i) for i in range(1, 101)) + "\n"
    all_path = _setup(
        monkeypatch, tmp_path, vdf=[1], api=[], cm=[], all_txt=prev
    )
    scan.main(allow_shrink=True)
    assert all_path.read_text(encoding="utf-8") == "1\n"


def test_non_suspicious_shrink_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Усадка выше порога floor (>= 50% от prev) — легитимна, запись проходит.
    prev = "\n".join(str(i) for i in range(1, 11)) + "\n"  # 10 ID
    all_path = _setup(
        monkeypatch,
        tmp_path,
        vdf=[1, 2, 3, 4, 5, 6],  # 6 >= 0.5*10
        api=[],
        cm=[],
        all_txt=prev,
    )
    scan.main(allow_shrink=False)
    assert all_path.read_text(encoding="utf-8") == "1\n2\n3\n4\n5\n6\n"


# ── (c) полностью пустой результат ──────────────────────────────────────────


def test_all_sources_empty_exits_without_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    all_path = _setup(monkeypatch, tmp_path, vdf=[], api=[], cm=[])
    with pytest.raises(SystemExit) as exc:
        scan.main()
    assert exc.value.code == 1
    assert not all_path.exists()


# ── (d) атомарность: нет остаточных tmp-файлов ─────────────────────────────


def test_no_leftover_tmp_after_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    all_path = _setup(monkeypatch, tmp_path, vdf=[10, 730], api=[440], cm=[999])
    scan.main()
    assert all_path.exists()
    assert list(tmp_path.glob(".all.txt.*.tmp")) == []


# ── (e) _read_api_ids: битая запись не роняет источник ─────────────────────


def test_read_api_ids_skips_records_without_appid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app.steam,
        "fetch_owned_games",
        lambda key, sid: [{"name": "x"}, {"appid": 730, "name": "y"}],
    )
    captured: dict[int, str] = {}
    monkeypatch.setattr(
        scan, "save_game_names", lambda names: captured.update(names)
    )
    result = scan._read_api_ids("key", _STEAM_ID)
    assert result == [730]
    assert captured == {730: "y"}


def test_read_api_ids_name_save_failure_keeps_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        app.steam,
        "fetch_owned_games",
        lambda key, sid: [
            {"appid": 730, "name": "y"},
            {"appid": 440, "name": "z"},
        ],
    )

    def _boom(names: dict[int, str]) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(scan, "save_game_names", _boom)
    # Сбой записи имён не должен ронять список App ID.
    result = scan._read_api_ids("key", _STEAM_ID)
    assert result == [730, 440]
