"""Автоматизация окна SAM Manager — Unlock All → Commit Changes → закрыть popup."""

from __future__ import annotations

import logging
import time

from pywinauto import Application, keyboard, mouse

from ..exceptions import SAMGameError
from ..unlock_result import UnlockResult
from .sam_status import _check_game_status

log = logging.getLogger("sam_automation")

# Таймаут перепроверки статистики после Refresh (сек). Короче load_timeout:
# если Refresh не помог за это время — игру откидываем в retry, не висим ещё
# раз полный load_timeout (всё равно отбросит — нет смысла ждать долго).
_REFRESH_RECHECK_TIMEOUT = 8.0


# ---------------------------------------------------------------------------
#  Кэш координат кнопок (вычисляется один раз на первой игре)
# ---------------------------------------------------------------------------


class _ButtonCache:
    """Хранит смещения кнопок относительно окна SAM.Game.

    Все окна SAM.Game имеют одинаковый layout — координаты кнопок
    одинаковы относительно rect окна. Вычисляем один раз через UIA,
    потом кликаем напрямую по координатам — мгновенно.
    """

    def __init__(self) -> None:
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
                        if (
                            child.friendly_class_name() == "Button"
                            and "unlock all" in child.window_text().lower()
                        ):
                            br = child.rectangle()
                            self.unlock_all_dx = (
                                br.left + br.right
                            ) // 2 - wr.left
                            self.unlock_all_dy = (
                                br.top + br.bottom
                            ) // 2 - wr.top
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
        """True если калибровка выполнена и координаты кнопок известны."""
        return self._calibrated


# Глобальный кэш — живёт весь процесс
_cache = _ButtonCache()


def _click_refresh(game_window) -> bool:
    """Находит и нажимает кнопку Refresh в _MainToolStrip SAM.Game.

    Используется когда статистика не загрузилась за timeout — Refresh
    заставляет SAM перезапросить достижения у Steam.

    _MainToolStrip — прямой child окна, Refresh — прямой child тулбара,
    поэтому идём по children() (быстро), а не descendants(): полный обход
    UIA на зависшем окне ~5с и не успевает за прерыванием.
    """
    try:
        for ctrl in game_window.children():
            try:
                if ctrl.automation_id() != "_MainToolStrip":
                    continue
                for btn in ctrl.children():
                    try:
                        if (
                            btn.friendly_class_name() == "Button"
                            and "refresh" in btn.window_text().lower()
                        ):
                            btn.click_input()
                            return True
                    except Exception:
                        continue
                return False
            except Exception:
                continue
    except Exception:
        pass
    return False


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
    skip_reason, total = _check_game_status(game_window, timeout=load_timeout)

    # Статистика не успела — даём ОДИН шанс через Refresh
    if skip_reason == "retry":
        if _click_refresh(game_window):
            log.info("Статистика не загрузилась — Refresh, повтор")
            skip_reason, total = _check_game_status(
                game_window, timeout=_REFRESH_RECHECK_TIMEOUT
            )
        # Не загрузилась даже после Refresh — это не временно (нет статистики /
        # playtest и пр.), откидываем как error, а не крутим вечный retry.
        if skip_reason == "retry":
            skip_reason = "error"

    if skip_reason:
        status = (
            "NO ACHIEVEMENTS" if skip_reason == "no achievements" else "ERROR"
        )
        log.info("APP STATUS: %s", status)
        return UnlockResult(
            game_id=game_id, skipped=True, skip_reason=skip_reason
        )

    # Калибровка кэша (только первый раз — ~1с, потом 0с)
    if not _cache.ready:
        if not _cache.calibrate(game_window):
            raise SAMGameError(
                game_id, "Не удалось найти кнопки (нет достижений?)"
            )
        log.info(
            "Кэш координат: unlock=(%d,%d) commit=(%d,%d)",
            _cache.unlock_all_dx,
            _cache.unlock_all_dy,
            _cache.commit_dx,
            _cache.commit_dy,
        )

    # --- Всё ниже — чистые coordinate clicks, без UIA ---

    wr = game_window.rectangle()

    # Unlock All
    mouse.click(
        coords=(wr.left + _cache.unlock_all_dx, wr.top + _cache.unlock_all_dy)
    )
    log.info("Unlock All")

    # Commit Changes
    time.sleep(0.05)
    mouse.click(coords=(wr.left + _cache.commit_dx, wr.top + _cache.commit_dy))

    # Enter для popup
    time.sleep(0.05)
    keyboard.send_keys("{ENTER}")

    if post_commit_delay > 0:
        time.sleep(post_commit_delay)

    if total == 0:
        log.info("APP STATUS: NO ACHIEVEMENTS")
        return UnlockResult(
            game_id=game_id, skipped=True, skip_reason="no achievements"
        )

    result.total = total
    result.newly_unlocked = total
    log.info("APP STATUS: UNLOCK (+%d)", total)
    return result
