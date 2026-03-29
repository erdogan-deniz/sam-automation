"""Определение оставшихся card drops через Steam Community страницы.

Использует веб-сессию, полученную через Steam CM протокол (steam_cm.get_web_cookies),
для аутентифицированных запросов к steamcommunity.com.
"""

from __future__ import annotations

import http.cookiejar
import logging
import time
import urllib.error
import urllib.request

from .card_parsers import _BadgesPageParser, _GameCardsParser

log = logging.getLogger("sam_automation")

_COMMUNITY_BASE = "https://steamcommunity.com"
_REQUEST_DELAY = 1.0  # секунд между запросами (rate limit)


# ---------------------------------------------------------------------------
#  HTTP с куки-сессией
# ---------------------------------------------------------------------------


def _make_opener(cookies: dict | None = None) -> urllib.request.OpenerDirector:
    """Создаёт urllib opener с куками Steam Community (куки опциональны)."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar)
    )
    opener.addheaders = [
        (
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36",
        ),
        ("Accept-Language", "en-US,en;q=0.9"),
    ]
    if cookies:
        cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
        opener.addheaders.append(("Cookie", cookie_str))
    return opener


def _fetch_page(opener: urllib.request.OpenerDirector, url: str) -> str:
    """Выполняет GET-запрос, возвращает текст страницы."""
    try:
        with opener.open(url, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} при запросе {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ошибка подключения к {url}: {e.reason}") from e


# ---------------------------------------------------------------------------
#  Публичный API
# ---------------------------------------------------------------------------


def fetch_games_with_card_drops(
    cookies: dict | None,
    steam_id: str,
) -> list[tuple[int, int]]:
    """Возвращает список (appid, cards_remaining) для всех игр с оставшимися дропами.

    Args:
        cookies:  веб-куки из steam_cm.get_web_cookies()
        steam_id: Steam ID 64 (17-значное число)

    Returns:
        Список кортежей (appid, cards_remaining), отсортированный по cards_remaining.
    """
    opener = _make_opener(cookies)
    results: list[tuple[int, int]] = []
    page = 1
    prev_html_size = 0  # для детектирования повторяющихся страниц

    while True:
        url = (
            f"{_COMMUNITY_BASE}/profiles/{steam_id}/badges/?l=english&p={page}"
        )
        log.debug("Получаю страницу значков: %s", url)
        try:
            html = _fetch_page(opener, url)
        except RuntimeError as e:
            log.warning(
                "Ошибка при получении страницы значков (стр. %d): %s", page, e
            )
            break

        log.debug("Получено %d байт для стр. %d", len(html), page)

        # Детектируем повторяющиеся страницы (Steam возвращает последнюю страницу снова)
        if page > 1 and len(html) == prev_html_size:
            log.debug(
                "Стр. %d: размер совпадает с предыдущей — конец пагинации", page
            )
            break
        prev_html_size = len(html)

        # Определяем причину пустого результата: приватный профиль vs. конец пагинации
        if "profile_private" in html or "This profile is private" in html:
            log.warning(
                "Профиль Steam Community приватный. "
                "Открой https://steamcommunity.com/profiles/%s/badges/ в браузере — "
                "если страница просит логин, измени настройки приватности профиля "
                "(Steam → Профиль → Редактировать → Приватность → Игры: Публично).",
                steam_id,
            )
            break
        if (
            'id="responsive_page_template_content"' in html
            and "badge_row" not in html
        ):
            log.warning(
                "Страница значков загружена, но badge_row не найден. "
                "Возможно, Steam изменил структуру HTML или нет игр с карточками."
            )

        log.debug(
            "Стр. %d: card_drop_info_dialog=%s",
            page,
            "card_drop_info_dialog" in html,
        )

        parser = _BadgesPageParser()
        parser.feed(html)

        if parser.badge_row_count == 0:
            # Нет badge_row — вышли за пределы пагинации
            break

        log.debug(
            "Стр. %d: badge_rows=%d, с дропами=%d",
            page,
            parser.badge_row_count,
            len(parser.games),
        )
        results.extend(parser.games)

        page += 1
        time.sleep(_REQUEST_DELAY)

    results.sort(key=lambda x: x[1])
    log.info("Обнаружено %d приложений библиотеки Steam с доступными картами на выпадение", len(results))
    return results


def check_cards_remaining(
    cookies: dict | None,
    steam_id: str,
    appid: int,
) -> int:
    """Проверяет количество оставшихся card drops для одной игры.

    Args:
        cookies:  веб-куки из steam_cm.get_web_cookies()
        steam_id: Steam ID 64
        appid:    App ID игры

    Returns:
        Количество оставшихся дропов (0 = карты закончились, -1 = не удалось определить).
    """
    opener = _make_opener(cookies)
    url = f"{_COMMUNITY_BASE}/profiles/{steam_id}/gamecards/{appid}/?l=english"
    log.debug("[%d] Проверяю card drops: %s", appid, url)
    try:
        html = _fetch_page(opener, url)
    except RuntimeError as e:
        log.warning("[%d] Ошибка при проверке card drops: %s", appid, e)
        return -1

    parser = _GameCardsParser()
    parser.feed(html)
    log.debug("[%d] Cards remaining: %d", appid, parser.cards_remaining)
    return parser.cards_remaining
