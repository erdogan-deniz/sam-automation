"""Чтение списка приложений из локальных файлов Steam (localconfig.vdf)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

from .steam_registry import find_steam_path, steamid64_to_id3  # noqa: F401

log = logging.getLogger("sam_automation")

# Канонический путь до блока приложений внутри localconfig.vdf. App ID —
# это numeric-ключи, лежащие НЕПОСРЕДСТВЕННО (depth=1) внутри этого блока.
_APPS_PATH: tuple[str, ...] = ("Software", "Valve", "Steam", "apps")


def _iter_vdf_tokens(content: str) -> Iterator[tuple[str, str]]:
    """Токенизирует VDF-текст в поток ('s', value) | ('{', '') | ('}', '').

    Quote-aware: строковый литерал ограничен неэкранированными кавычками, поэтому
    любые `{`/`}` внутри значения (напр. `"LaunchOptions" "gamemoderun }"`)
    поглощаются как содержимое строки и НЕ порождают скобочных токенов. Это
    убирает разрыв/растягивание блока при балансировке скобок.
    """
    i, n = 0, len(content)
    while i < n:
        c = content[i]
        if c == '"':
            i += 1
            buf: list[str] = []
            while i < n:
                ch = content[i]
                if ch == "\\" and i + 1 < n:
                    # Экранированная последовательность (\\, \", \n …): следующий
                    # символ — литерал, кавычку строки он не закрывает.
                    buf.append(content[i + 1])
                    i += 2
                    continue
                if ch == '"':
                    i += 1
                    break
                buf.append(ch)
                i += 1
            yield ("s", "".join(buf))
        elif c == "{":
            yield ("{", "")
            i += 1
        elif c == "}":
            yield ("}", "")
            i += 1
        else:
            i += 1


def _extract_app_ids_from_vdf(content: str) -> list[int]:
    """Извлекает App ID (numeric-ключи depth=1 в apps) из localconfig.vdf.

    Структура localconfig.vdf:
        "UserLocalConfigStore"
        {
            "Software" { "Valve" { "Steam" { "apps" {
                "10"  { "LastPlayed" "..." }
                ...

    Обход quote-aware токенайзером с отслеживанием пути блоков (стек ключей):
    numeric-ключ засчитывается App ID ТОЛЬКО если его прямой родитель — apps под
    Software/Valve/Steam (depth=1 внутри apps). Это отсекает фантомы из вложенных
    структур (`depots { "228987" { … } }`, ключ `"0"` и т.п.). apps ищется как
    прямой ребёнок Steam, но НЕ обязан быть первым (терпит скаляры SurveyDate
    до неё). Результат дедуплицируется с сохранением порядка.
    """
    stack: list[str | None] = []
    app_ids: list[int] = []
    seen: set[str] = set()
    apps_found = False
    depth = 0
    underflow = False
    pending: str | None = None  # строковый ключ, ждущий своего продолжения

    for kind, val in _iter_vdf_tokens(content):
        if kind == "s":
            if pending is not None:
                # "key" "value" — скалярная пара, оба токена расходуются.
                pending = None
            else:
                pending = val
            continue
        if kind == "{":
            if pending is not None:
                # pending — ключ, открывающий блок.
                if pending == "apps" and tuple(stack[-3:]) == _APPS_PATH[:3]:
                    apps_found = True
                # isdecimal (не isdigit): App ID — ASCII-десятичные; isdigit
                # True и для юникод-«цифр» (², ①), на которых int() бросает
                # ValueError и роняет чтение ВСЕЙ библиотеки.
                if pending.isdecimal() and tuple(stack[-4:]) == _APPS_PATH:
                    if pending not in seen:
                        seen.add(pending)
                        app_ids.append(int(pending))
                stack.append(pending)
                pending = None
            else:
                # Осиротевшая `{` без ключа — держим глубину согласованной.
                stack.append(None)
            depth += 1
            continue
        # kind == "}"
        pending = None  # висячий ключ перед закрытием — отбрасываем
        if stack:
            stack.pop()
        depth -= 1
        if depth < 0:
            underflow = True
            depth = 0

    if not apps_found:
        log.warning("Секция 'Software/Valve/Steam/apps' не найдена в VDF файле")
    if depth != 0 or underflow:
        log.warning(
            "VDF файл повреждён/обрезан (несбалансированные скобки) — "
            "распарсено %d App ID, возможны потери",
            len(app_ids),
        )

    return app_ids


def read_library_app_ids(steam_path: str, steam_id: str) -> list[int]:
    """Читает все App ID из localconfig.vdf — полная библиотека включая демо и ПО.

    Args:
        steam_path: путь к папке Steam (например C:/Program Files (x86)/Steam)
        steam_id: Steam ID64 пользователя (17 цифр)

    Returns:
        Список всех App ID из библиотеки.
    """
    id3 = steamid64_to_id3(steam_id)
    vdf_path = (
        Path(steam_path) / "userdata" / str(id3) / "config" / "localconfig.vdf"
    )

    if not vdf_path.exists():
        raise FileNotFoundError(
            f"Локальный Steam файл localconfig.vdf не найден: {vdf_path}\n"
            f"Убедись, что: путь к Steam файлу указан верно и Вы вошли в Steam."
        )

    log.info(
        "Получение ID приложений библиотеки Steam из локального файла: %s",
        vdf_path,
    )

    content = vdf_path.read_text(encoding="utf-8", errors="replace")
    app_ids = _extract_app_ids_from_vdf(content)

    log.info(
        "Найдено %d ID приложений библиотеки Steam из локального файла",
        len(app_ids),
    )

    return app_ids
