"""HTML парсеры для Steam Community страниц карточек.

Используются в app.card_checker для разбора страниц:
  /profiles/{steamid}/badges/     → _BadgesPageParser
  /profiles/{steamid}/gamecards/  → _GameCardsParser
"""

from __future__ import annotations

import re
from html.parser import HTMLParser


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

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
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
            if (
                self._drops_depth is not None
                and self._div_depth == self._drops_depth
            ):
                # Выходим из badge_title_stats_drops — сохраняем если нашли оба значения
                if (
                    self._pending_drops is not None
                    and self._pending_appid is not None
                ):
                    self.games.append(
                        (self._pending_appid, self._pending_drops)
                    )
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

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
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
