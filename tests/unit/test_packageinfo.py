"""Тесты разбора packageinfo.vdf (app/steam/packageinfo.py).

Один структурно битый пакет НЕ должен ронять весь разбор (иначе 0 CM-игр).
parse_packageinfo мокается — проверяется только собственная устойчивость
итерации по пакетам, а не бинарный формат Valve.
"""

from __future__ import annotations

import os

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

from pathlib import Path  # noqa: E402

import app.steam.packageinfo as pkgmod  # noqa: E402


def _mk_pkginfo(tmp_path: Path) -> Path:
    (tmp_path / "appcache").mkdir()
    f = tmp_path / "appcache" / "packageinfo.vdf"
    f.write_bytes(b"\x00")  # содержимое не важно: parse_packageinfo мокается
    return tmp_path


def _patch_parse(monkeypatch, packages):
    def fake_parse(_f):
        return ({}, iter(packages))

    monkeypatch.setattr("steam.utils.appcache.parse_packageinfo", fake_parse)


def test_broken_package_is_skipped_others_parsed(tmp_path, monkeypatch):
    steam_path = _mk_pkginfo(tmp_path)
    good1 = {"packageid": 1, "data": {"1": {"appids": {"0": 10, "1": 11}}}}
    broken = {"packageid": 2, "data": None}  # .get на None → AttributeError
    good2 = {"packageid": 3, "data": {"3": {"appids": {"0": 30}}}}
    _patch_parse(monkeypatch, [good1, broken, good2])

    result = pkgmod.expand_packages_to_apps(str(steam_path), {1, 2, 3})

    assert sorted(result) == [10, 11, 30]


def test_non_int_appid_is_dropped(tmp_path, monkeypatch):
    steam_path = _mk_pkginfo(tmp_path)
    pkg = {
        "packageid": 1,
        "data": {"1": {"appids": {"0": 10, "1": "bad", "2": 12}}},
    }
    _patch_parse(monkeypatch, [pkg])

    result = pkgmod.expand_packages_to_apps(str(steam_path), {1})

    assert sorted(result) == [10, 12]


def test_first_broken_package_does_not_abort(tmp_path, monkeypatch):
    # Битый пакет ПЕРВЫМ в потоке — остальные всё равно разбираются.
    steam_path = _mk_pkginfo(tmp_path)
    broken = {"packageid": 1, "data": 42}  # int.get → AttributeError
    good = {"packageid": 2, "data": {"2": {"appids": {"0": 20}}}}
    _patch_parse(monkeypatch, [broken, good])

    result = pkgmod.expand_packages_to_apps(str(steam_path), {1, 2})

    assert result == [20]


def test_broken_owned_package_counted_as_missing(tmp_path, monkeypatch, caplog):
    # Битый ВЛАДЕЕМЫЙ пакет должен считаться «пропущенным» в логе (раньше
    # found_pkgs++ шёл ДО разбора → пакет ложно числился найденным, missing=0).
    import logging

    steam_path = _mk_pkginfo(tmp_path)
    good = {"packageid": 1, "data": {"1": {"appids": {"0": 10}}}}
    broken = {"packageid": 2, "data": None}  # owned, но .get на None → ошибка
    _patch_parse(monkeypatch, [good, broken])

    with caplog.at_level(logging.INFO, logger="sam_automation"):
        result = pkgmod.expand_packages_to_apps(str(steam_path), {1, 2})

    assert result == [10]
    # owned={1,2}, успешно разобран только good → пропущен 1.
    assert "пропущено пакетов: 1" in caplog.text


def test_stream_level_corruption_returns_partial(tmp_path, monkeypatch):
    # Повреждение на уровне ПОТОКА (генератор рушится в середине итерации), а не
    # отдельного пакета: уже распарсенное возвращается, а не теряются ВСЕ CM-игры
    # (иначе исключение всплывает мимо per-package try/except).
    steam_path = _mk_pkginfo(tmp_path)
    good = {"packageid": 1, "data": {"1": {"appids": {"0": 10}}}}

    def _bad_gen():
        yield good
        raise ValueError("corrupt binary stream")

    def fake_parse(_f):
        return ({}, _bad_gen())

    monkeypatch.setattr("steam.utils.appcache.parse_packageinfo", fake_parse)

    result = pkgmod.expand_packages_to_apps(str(steam_path), {1})

    assert result == [10]
