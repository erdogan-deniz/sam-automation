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


@pytest.fixture(autouse=True)
def _no_real_sam_process_kills(monkeypatch: pytest.MonkeyPatch) -> None:
    """Тесты не видят и не убивают настоящие SAM.Game.exe.

    Иначе `pytest` во время живого фарма убивал его процессы: тест доходил до
    настоящего kill_all_sam_games (свип по всем SAM.Game.exe машины). Тест,
    которому нужны эти функции, подменяет их сам — его monkeypatch главнее.
    """
    import app.sam.launcher as launcher
    import app.sam.picker_session as picker_session

    def _refuse_kill(pid: int) -> None:
        raise AssertionError(f"тест пытался убить настоящий процесс PID={pid}")

    for mod in (launcher, picker_session):
        monkeypatch.setattr(mod, "_get_sam_game_pids", set)
        monkeypatch.setattr(mod, "_kill_pid", _refuse_kill)
