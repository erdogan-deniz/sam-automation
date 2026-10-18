"""Тесты app/cli.py: регистр имён флагов не важен, значения не трогаются."""

from __future__ import annotations

from app.cli import casefold_options


def test_lowercases_long_option_names() -> None:
    assert casefold_options(["--DLC", "--Add"]) == ["--dlc", "--add"]


def test_keeps_values_as_is() -> None:
    assert casefold_options(["--Name", "Foo", "--Path=C:/Bar"]) == [
        "--name",
        "Foo",
        "--path=C:/Bar",
    ]


def test_leaves_short_options_and_positionals() -> None:
    assert casefold_options(["-H", "ABC"]) == ["-H", "ABC"]


def test_stops_after_double_dash() -> None:
    assert casefold_options(["--X", "--", "--Y"]) == ["--x", "--", "--Y"]
