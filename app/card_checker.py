"""Определение оставшихся card drops через Steam Community страницы.

Использует веб-сессию, полученную через Steam CM протокол (steam_cm.get_web_cookies),
для аутентифицированных запросов к steamcommunity.com.
"""

from __future__ import annotations

import http.cookiejar
import logging
import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser

log = logging.getLogger("sam_automation")

_COMMUNITY_BASE = "https://steamcommunity.com"
_REQUEST_DELAY = 1.0  # секунд между запросами (rate limit)


# ---------------------------------------------------------------------------
#  HTTP с куки-сессией
# ---------------------------------------------------------------------------

def _make_opener(cookies: dict | None = None) -> urllib.request.OpenerDirector:
    """Создаёт urllib opener с куками Steam Community (куки опциональны)."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [
        ("User-Agent",
         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
         "AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/120.0.0.0 Safari/537.36"),
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
#  HTML парсеры
# ---------------------------------------------------------------------------

class _BadgesPageParser(HTMLParser):
    """Парсит страницу /badges/ и собирает (appid, cards_remaining).

    Реальная структура HTML (из браузера):
      <div class="badge_title_stats_drops">
        <span class="progress_info_bold">1 card drop remaining</span>
        <div class="card_drop_info_dialog" id="card_drop_info_gamebadge_3593520_1_0" style="display: none;">
        </div>
      </div>

    progress_info_bold идёт ДО card_drop_info_dialog (они соседи, не вложены).
    Appid берётся из id атрибута: gamebadge_{appid}_{level}_{border}.
    Значения накапливаются и записываются при выходе из badge_title_stats_drops.
    """

    def __init__(self) -> None:
        super().__init__()
        self.games: list[tuple[int, int]] = []
        self.badge_row_count = 0  # для пагинации
        self._div_depth = 0
        self._drops_depth: int | None = None  # глубина badge_title_stats_drops
        self._pending_drops: int | None = None
        self._pending_appid: int | None = None
        self._capture = False
        self._text = ""

    @property
    def _in_drops(self) -> bool:
        return self._drops_depth is not None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "") or ""

        if tag == "div":
            self._div_depth += 1
            if "badge_row" in cls:
                self.badge_row_count += 1
            # Контейнер с информацией о дропах
            if "badge_title_stats_drops" in cls:
                self._drops_depth = self._div_depth
                self._pending_drops = None
                self._pending_appid = None
            # Appid из id соседнего div: card_drop_info_gamebadge_{appid}_{level}_{border}
            if "card_drop_info_dialog" in cls and self._in_drops:
                div_id = attrs_dict.get("id", "") or ""
                m = re.search(r"gamebadge_(\d+)_", div_id)
                if m:
                    self._pending_appid = int(m.group(1))

        if tag == "span" and "progress_info_bold" in cls and self._in_drops:
            self._capture = True
            self._text = ""

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._capture:
            self._capture = False
            text = self._text.strip()
            m = re.search(r"(\d+)\s+card\s+drop", text, re.IGNORECASE)
            if m:
                self._pending_drops = int(m.group(1))

        if tag == "div":
            if self._drops_depth is not None and self._div_depth == self._drops_depth:
                # Выходим из badge_title_stats_drops — сохраняем если нашли оба значения
                if self._pending_drops is not None and self._pending_appid is not None:
                    self.games.append((self._pending_appid, self._pending_drops))
                self._drops_depth = None
                self._pending_drops = None
                self._pending_appid = None
            self._div_depth -= 1


class _GameCardsParser(HTMLParser):
    """Парсит страницу /gamecards/{appid}/ и извлекает cards_remaining."""

    def __init__(self) -> None:
        super().__init__()
        self.cards_remaining: int = -1
        self._capture = False
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = dict(attrs).get("class", "") or ""
        if tag == "span" and "progress_info_bold" in cls:
            self._capture = True
            self._text = ""

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._capture:
            self._capture = False
            text = self._text.strip()
            m = re.search(r"(\d+)\s+card\s+drop", text, re.IGNORECASE)
            if m:
                self.cards_remaining = int(m.group(1))
            elif re.search(r"no card drops", text, re.IGNORECASE):
                self.cards_remaining = 0


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
        url = f"{_COMMUNITY_BASE}/profiles/{steam_id}/badges/?l=english&p={page}"
        log.debug("Получаю страницу значков: %s", url)
        try:
            html = _fetch_page(opener, url)
        except RuntimeError as e:
            log.warning("Ошибка при получении страницы значков (стр. %d): %s", page, e)
            break

        log.debug("Получено %d байт для стр. %d", len(html), page)

        # Детектируем повторяющиеся страницы (Steam возвращает последнюю страницу снова)
        if page > 1 and len(html) == prev_html_size:
            log.debug("Стр. %d: размер совпадает с предыдущей — конец пагинации", page)
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
        if 'id="responsive_page_template_content"' in html and "badge_row" not in html:
            log.warning(
                "Страница значков загружена, но badge_row не найден. "
                "Возможно, Steam изменил структуру HTML или нет игр с карточками."
            )

        log.debug(
            "Стр. %d: card_drop_info_dialog=%s",
            page, "card_drop_info_dialog" in html,
        )

        parser = _BadgesPageParser()
        parser.feed(html)

        if parser.badge_row_count == 0:
            # Нет badge_row — вышли за пределы пагинации
            break

        log.debug("Стр. %d: badge_rows=%d, с дропами=%d", page, parser.badge_row_count, len(parser.games))
        results.extend(parser.games)

        page += 1
        time.sleep(_REQUEST_DELAY)

    results.sort(key=lambda x: x[1])
    log.info("Итого игр с card drops: %d", len(results))
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
