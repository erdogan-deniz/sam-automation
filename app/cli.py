"""Общее для CLI-скриптов `scripts/`."""

from __future__ import annotations

from collections.abc import Sequence


def casefold_options(argv: Sequence[str]) -> list[str]:
    """Имена длинных флагов — в нижний регистр: `--DLC`, `--Dlc` → `--dlc`.

    Значения не трогаются: в `--interval 0.5` значение — отдельный аргумент,
    а в `--name=Foo` меняется только часть до «=». Всё после `--` остаётся
    как есть.
    """
    out: list[str] = []
    passthrough = False
    for arg in argv:
        if passthrough or not arg.startswith("--"):
            out.append(arg)
            continue
        if arg == "--":
            passthrough = True
            out.append(arg)
            continue
        name, sep, value = arg.partition("=")
        out.append(name.lower() + sep + value)
    return out
