"""Общие фикстуры для юнит-тестов."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest
import yaml


@pytest.fixture
def write_config(tmp_path: Path) -> Callable[..., str]:
    """Фабрика: пишет config.yaml в tmp_path и возвращает путь к нему."""

    def factory(**kwargs: Any) -> str:
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(kwargs, allow_unicode=True), encoding="utf-8")
        return str(path)

    return factory


@pytest.fixture
def ids_file(tmp_path: Path) -> Callable[..., Path]:
    """Фабрика: создаёт текстовый файл с ID и возвращает Path."""

    def factory(ids: list[Any], *, name: str = "ids.txt") -> Path:
        f: Path = tmp_path / name
        f.write_text("\n".join(str(i) for i in ids) + "\n", encoding="utf-8")
        return f

    return factory
