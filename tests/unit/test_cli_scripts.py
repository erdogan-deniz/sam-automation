"""Все CLI-скрипты принимают имена флагов в любом регистре (`--RESET`).

Каждый скрипт должен отдавать argparse уже `casefold_options(sys.argv[1:])`.
Перехватываем ArgumentParser.parse_args и останавливаем main() сразу на
разборе — дальше скрипт не идёт (ни конфига, ни Steam).
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


class _Parsed(Exception):
    pass


def _load(rel: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"cli_case_{rel.replace('/', '_')}", _SCRIPTS / rel
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize(
    ("rel", "entry"),
    [
        ("achievements/farm.py", "main"),
        ("playtime/boost.py", "main"),
        ("library/add_free.py", "main"),
        ("library/add_demos.py", "main"),
        ("library/wishlist_add.py", "main"),
        ("library/wishlist_clean.py", "main"),
        ("scan.py", "_parse_args"),
    ],
)
def test_script_lowercases_flag_names(monkeypatch, rel, entry) -> None:
    mod = _load(rel)
    seen: dict = {}

    def fake_parse_args(self, args=None, namespace=None):
        seen["args"] = args
        raise _Parsed

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", fake_parse_args)
    monkeypatch.setattr(sys, "argv", [rel, "--RESET", "--Limit=5"])

    with pytest.raises(_Parsed):
        getattr(mod, entry)()

    assert seen["args"] == ["--reset", "--limit=5"]
