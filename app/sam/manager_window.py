"""Автоматизация окна SAM Manager — Unlock All → Commit Changes → окно итога."""

from __future__ import annotations

import logging
import re
import time

from pywinauto import Application, mouse

from ..exceptions import SAMGameError, SAMGameNotOwned, SAMPickerBroken
from ..unlock_result import UnlockResult
from .sam_downloader import check_steam_running
from .sam_status import _check_game_status
from .win32_utils import _dialog_text, _foreground_pid, _take_dialog

log = logging.getLogger("sam_automation")

# Окно SAM.Game Manager: automation_id == "Manager" (как у Picker — "GamePicker").
# Заголовок содержит "Steam Achievement Manager" — запасной маркер.
_MANAGER_WINDOW_ID = "Manager"
_MANAGER_TITLE_MARK = "achievement manager"

# Минимум на ожидание появления окна Manager (сек). Окно-оболочка строится
# быстро, но бюджет не должен делиться с медленной загрузкой достижений.
_WINDOW_WAIT_FLOOR = 15.0


def _is_manager_window(win) -> bool:
    """True если окно — это Manager. Дешёвые проверки (без обхода children())."""
    try:
        if win.automation_id() == _MANAGER_WINDOW_ID:
            return True
    except Exception:
        pass
    try:
        if _MANAGER_TITLE_MARK in win.window_text().lower():
            return True
    except Exception:
        pass
    return False


def _find_manager_window(app: Application):
    """Возвращает окно SAM.Game Manager, иначе None.

    process_game раньше брал app.windows()[0] — ПЕРВОЕ появившееся окно. Если
    SAM показывал переходное/служебное окно, а Manager подменял его позже,
    ссылка указывала на не то/мёртвое окно: всё через children() оказывалось
    пустым → каждая игра уходила в ложный ERROR. Выбираем окно по automation_id
    (дёшево, не виснет на children() зависшего окна).
    """
    try:
        wins = app.windows()
    except Exception:
        return None
    for win in wins:
        if _is_manager_window(win):
            return win
    return None


# Текст окна «Error» SAM.Game, когда Steam API не стартует для игры.
_STEAM_NOT_RUNNING_TEXT = "steam is not running"


def _steam_not_running_error(app: Application) -> bool:
    """True, если SAM.Game показал окно «Error» со «Steam is not running».

    Живьём 21.10.2026 SAM так отвечал при запущенном Steam на игры, которых
    нет в библиотеке. Ждать окно Manager после этого бессмысленно.
    """
    try:
        wins = app.windows()
    except Exception:
        return False
    for win in wins:
        try:
            if win.window_text() != "Error":
                continue
            text = _dialog_text(win.handle).lower()
        except Exception:
            continue
        if _STEAM_NOT_RUNNING_TEXT in text:
            return True
    return False


def _log_window_diag(app: Application, game_id: int) -> None:
    """Диагностика на провале детекта: какие окна открыты (id + заголовок).

    Только дешёвые свойства окна — children() на зависшем окне занимает ~5с,
    а сюда мы попадаем именно при подозрении на зависшее/не то окно.
    """
    try:
        wins = app.windows()
    except Exception as e:
        log.warning("ДИАГ %d: app.windows() упал: %s", game_id, e)
        return
    log.warning("ДИАГ %d: окно Manager не найдено; окон=%d", game_id, len(wins))
    for i, win in enumerate(wins):
        try:
            aid = win.automation_id()
        except Exception as e:
            aid = f"<err: {e}>"
        try:
            title = win.window_text()
        except Exception:
            title = "<?>"
        log.warning("ДИАГ %d:  окно[%d] id=%r title=%r", game_id, i, aid, title)


# МИНИМАЛЬНЫЙ таймаут перепроверки после Refresh (сек). Refresh перезапускает
# загрузку статистики с нуля, поэтому перепроверка ждёт max(load_timeout, этот
# минимум): игра, грузившаяся ~load_timeout, иначе детерминированно падала бы
# в ложный ERROR на короткой перепроверке.
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


# Окно итога Commit (живьём 22.10.2026): «Information» — «Stored N achievements
# and M statistics.»; сбой — «Error» с текстом причины.
_STORED_RE = re.compile(r"stored\s+(\d+)\s+achievements", re.IGNORECASE)
_PROTECTED_TEXT = "protected achievement"
_COMMIT_CONFIRM_TIMEOUT = 10.0  # сек на окно итога после Commit
_DIALOG_SETTLE = 0.5  # сек без новых окон — защищённые достижения закрыты


def _close_protected_dialogs(pid: int, game_id: int) -> int:
    """Закрывает окна «protected achievement» после Unlock All, считает их.

    SAM показывает модальное окно на КАЖДОЕ защищённое достижение по очереди;
    пока оно открыто, клик Commit не доходит.
    """
    closed = 0
    quiet_since = time.monotonic()
    while time.monotonic() - quiet_since < _DIALOG_SETTLE:
        dialog = _take_dialog(pid)
        if dialog is None:
            time.sleep(0.05)
            continue
        title, text = dialog
        if _PROTECTED_TEXT not in text.lower():
            raise SAMGameError(
                game_id, f"SAM после Unlock All: {text or title}"
            )
        closed += 1
        quiet_since = time.monotonic()
    return closed


def _await_stored(pid: int, game_id: int) -> int:
    """Ждёт окно итога Commit; возвращает число сохранённых достижений."""
    deadline = time.monotonic() + _COMMIT_CONFIRM_TIMEOUT
    while time.monotonic() < deadline:
        dialog = _take_dialog(pid)
        if dialog is None:
            time.sleep(0.05)
            continue
        title, text = dialog
        match = _STORED_RE.search(text)
        if match:
            return int(match.group(1))
        raise SAMGameError(game_id, f"SAM не сохранил: {text or title}")
    raise SAMGameError(game_id, "SAM не подтвердил сохранение")


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

    # Ждём именно окно Manager (по automation_id), пропуская переходные окна.
    # Бюджет — отдельный от загрузки достижений: окно-оболочка появляется
    # быстро, делить его с медленным списком нельзя.
    game_window = None
    wait_deadline = time.time() + max(load_timeout, _WINDOW_WAIT_FLOOR)
    while time.time() < wait_deadline:
        game_window = _find_manager_window(app)
        if game_window is not None:
            break
        if _steam_not_running_error(app):
            # Steam правда упал — сбой среды, не игры: farm перезапустит
            # Picker и остановится, а не запишет все игры в not_owned.
            if not check_steam_running():
                raise SAMPickerBroken("SAM.Game: Steam не запущен")
            raise SAMGameNotOwned(
                game_id, "нет в библиотеке (SAM: Steam is not running)"
            )
        time.sleep(0.1)

    if game_window is None:
        _log_window_diag(app, game_id)
        raise SAMGameError(game_id, "Окно Manager не найдено")

    # Ранний выход: нет достижений или SAM не смог их загрузить
    skip_reason, total = _check_game_status(game_window, timeout=load_timeout)

    # Статистика не успела ("retry"), SAM показал error (часто транзиент) или
    # «you don't own the game» — даём ОДИН шанс через Refresh + перепроверка.
    if skip_reason in ("retry", "error", "not owned"):
        # Окно могло подмениться за время загрузки — перевыберем Manager.
        refreshed = _find_manager_window(app)
        if refreshed is not None:
            game_window = refreshed
        clicked = _click_refresh(game_window)
        if not clicked:
            time.sleep(0.5)  # окно могло быть занято — одна повторная попытка
            clicked = _click_refresh(game_window)
        if clicked:
            log.info("Статистика не загрузилась — Refresh, повтор")
        else:
            # Перепроверяем даже без клика: первая загрузка могла дозавершиться
            log.warning("Кнопка Refresh не нажалась — перепроверка без неё")
        skip_reason, total = _check_game_status(
            game_window,
            timeout=max(load_timeout, _REFRESH_RECHECK_TIMEOUT),
        )
        # Не загрузилась даже после Refresh — откидываем как error
        # (retryable через --retry-errors), а не крутим вечный retry.
        if skip_reason == "retry":
            skip_reason = "error"
        if skip_reason == "not owned":
            raise SAMGameNotOwned(
                game_id, "нет в библиотеке (SAM: you don't own the game)"
            )

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

    # Координатные клики попадают только в АКТИВНОЕ окно: если SAM.Game не в
    # фокусе (пользователь переключился, окно за другим), клики уходят в чужое
    # окно. Поднимаем окно и проверяем, что на переднем плане именно SAM.Game.
    pid = game_window.process_id()
    try:
        game_window.set_focus()
    except Exception as e:
        log.warning("set_focus не удался: %s", e)
    if _foreground_pid() != pid:
        raise SAMGameError(
            game_id, "окно SAM.Game не на переднем плане — клики не дойдут"
        )
    _take_dialog(pid)  # старое окно-сообщение перехватило бы клики

    wr = game_window.rectangle()

    # Unlock All
    mouse.click(
        coords=(wr.left + _cache.unlock_all_dx, wr.top + _cache.unlock_all_dy)
    )
    log.info("Unlock All")
    protected = _close_protected_dialogs(pid, game_id)
    if protected:
        log.info("Защищённых достижений (SAM не меняет): %d", protected)

    # Commit Changes — итог читается из окна SAM, а не закрывается вслепую:
    # done только по подтверждённому сохранению (unverified ≠ done).
    mouse.click(coords=(wr.left + _cache.commit_dx, wr.top + _cache.commit_dy))
    stored = _await_stored(pid, game_id)

    if post_commit_delay > 0:
        time.sleep(post_commit_delay)

    result.total = total
    result.newly_unlocked = stored
    log.info("APP STATUS: UNLOCK (+%d)", stored)
    return result
