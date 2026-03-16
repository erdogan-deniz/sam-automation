"""Автоматизация окна SAM Manager — Unlock All → Commit Changes → закрыть popup."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

from pywinauto import Application, mouse, keyboard

from .exceptions import SAMGameError

log = logging.getLogger("sam_automation")


@dataclass
class UnlockResult:
    """Результат обработки одной игры."""
    game_id: int
    total: int = 0
    already_unlocked: int = 0
    newly_unlocked: int = 0
    skipped: bool = False
    skip_reason: str = ""


# ---------------------------------------------------------------------------
#  Кэш координат кнопок (вычисляется один раз на первой игре)
# ---------------------------------------------------------------------------

class _ButtonCache:
    """Хранит смещения кнопок относительно окна SAM.Game.

    Все окна SAM.Game имеют одинаковый layout — координаты кнопок
    одинаковы относительно rect окна. Вычисляем один раз через UIA,
    потом кликаем напрямую по координатам — мгновенно.
    """

    def __init__(self):
        self.unlock_all_dx: int = 0
        self.unlock_all_dy: int = 0
        self.commit_dx: int = 0
        self.commit_dy: int = 0
        self._calibrated = False

    def calibrate(self, game_window) -> bool:
        """Сканирует descendants один раз, запоминает смещения."""
        wr = game_window.rectangle()

        for ctrl in game_window.descendants():
            try:
                aid = ctrl.automation_id()
                if aid == "_AchievementsToolStrip":
                    for child in ctrl.children():
                        if child.friendly_class_name() == "Button" and "unlock all" in child.window_text().lower():
                            br = child.rectangle()
                            self.unlock_all_dx = (br.left + br.right) // 2 - wr.left
                            self.unlock_all_dy = (br.top + br.bottom) // 2 - wr.top
                elif aid == "_MainToolStrip":
                    tr = ctrl.rectangle()
                    self.commit_dx = tr.right - wr.left - 40
                    self.commit_dy = (tr.top + tr.bottom) // 2 - wr.top
            except Exception:
                continue

        self._calibrated = self.unlock_all_dx > 0 and self.commit_dx > 0
        return self._calibrated

    @property
    def ready(self) -> bool:
        return self._calibrated


_LOADING_TEXT = "retrieving stat information"


def _read_status_panel(game_window) -> str:
    """Читает текст из панелей StatusBar (ToolStripStatusLabel), lowercase."""
    for ctrl in game_window.children():
        try:
            if ctrl.friendly_class_name() != "StatusBar":
                continue
            text = ctrl.window_text().strip()
            if text:
                return text.lower()
            for panel in ctrl.children():
                try:
                    text = panel.window_text().strip()
                    if text:
                        return text.lower()
                except Exception:
                    pass
        except Exception:
            pass
    return ""


def _wait_for_status(game_window, timeout: float = 8.0, settle: float = 0.5) -> str:
    """Ждёт стабильного финального состояния статус-бара, возвращает lowercase.

    SAM проходит через транзитные состояния: 'Retrieving...' → 'Error...' → 'X achievements'.
    Возвращает текст только когда он не менялся >= settle секунд подряд.
    Если за timeout так и не стабилизировался — возвращает последний виденный текст.
    """
    deadline = time.time() + timeout
    last = ""
    stable_since: float = 0.0

    while time.time() < deadline:
        text = _read_status_panel(game_window)
        if text and not text.startswith(_LOADING_TEXT):
            if text != last:
                last = text
                stable_since = time.time()
            elif time.time() - stable_since >= settle:
                log.debug("Статус-бар (стабильный): %r", text)
                return last
        time.sleep(0.1)

    log.debug("Статус-бар не стабилизировался за %.1fs, последний: %r", timeout, last)
    return last


def _check_game_status(game_window) -> tuple[str | None, int]:
    """Читает статус-бар SAM.Game. Возвращает (skip_reason | None, achievement_count).

    skip_reason:
        None             — OK, достижения загружены
        "no achievements" — у игры нет достижений (постоянный пропуск)
        "error"          — SAM не смог загрузить достижения (временная ошибка, можно повторить)
    """
    status = _wait_for_status(game_window, timeout=3.0, settle=0.5)
    match = re.search(r'(\d+)\s+achievement', status)
    if match:
        count = int(match.group(1))
        return (None, count) if count > 0 else ("no achievements", 0)
    if "error" in status:
        return "error", 0
    return "no achievements", 0


# Глобальный кэш — живёт весь процесс
_cache = _ButtonCache()


# ---------------------------------------------------------------------------
#  Основная функция обработки игры (fast path)
# ---------------------------------------------------------------------------

def process_game(
    app: Application,
    game_id: int,
    load_timeout: float = 10.0,
    post_commit_delay: float = 0.0,
) -> UnlockResult:
    """Unlock All → Commit Changes → Enter.

    Первый вызов: сканирует UIA, кэширует координаты кнопок.
    Последующие вызовы: только coordinate clicks — мгновенно.
    """
    result = UnlockResult(game_id=game_id)

    # Ждём окно через app.windows() (обход бага find_element с 32-бит)
    game_window = None
    wait_deadline = time.time() + load_timeout
    while time.time() < wait_deadline:
        wins = app.windows()
        if wins:
            game_window = wins[0]
            break
        time.sleep(0.05)

    if game_window is None:
        raise SAMGameError(game_id, "Окно Manager не появилось")

    # Ранний выход: нет достижений или SAM не смог их загрузить
    skip_reason, total = _check_game_status(game_window)
    if skip_reason:
        log.info("[%d] Пропуск: %s", game_id, skip_reason)
        return UnlockResult(game_id=game_id, skipped=True, skip_reason=skip_reason)

    # Калибровка кэша (только первый раз — ~1с, потом 0с)
    if not _cache.ready:
        if not _cache.calibrate(game_window):
            raise SAMGameError(game_id, "Не удалось найти кнопки (нет достижений?)")
        log.info("Кэш координат: unlock=(%d,%d) commit=(%d,%d)",
                 _cache.unlock_all_dx, _cache.unlock_all_dy,
                 _cache.commit_dx, _cache.commit_dy)

    # --- Всё ниже — чистые coordinate clicks, без UIA ---

    wr = game_window.rectangle()

    # Unlock All
    mouse.click(coords=(wr.left + _cache.unlock_all_dx,
                        wr.top + _cache.unlock_all_dy))
    log.info("[%d] Unlock All", game_id)

    # Commit Changes
    time.sleep(0.05)
    mouse.click(coords=(wr.left + _cache.commit_dx,
                        wr.top + _cache.commit_dy))

    # Enter для popup
    time.sleep(0.05)
    keyboard.send_keys("{ENTER}")

    if post_commit_delay > 0:
        time.sleep(post_commit_delay)

    result.total = total
    result.newly_unlocked = total
    log.info("[%d] Done", game_id)
    return result
