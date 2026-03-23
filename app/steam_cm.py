"""Получение App ID через Steam CM протокол — по лицензиям аккаунта.

Алгоритм:
  1. Логин в Steam CM (сохранённые данные или интерактивный ввод пароля/2FA)
  2. Получаем список owned пакетов из client.licenses
  3. Разворачиваем пакеты → App ID через локальный packageinfo.vdf
  4. После успешного входа предлагается сохранить данные на диск

Пароль хранится в Windows Credential Manager через keyring (DPAPI-шифрование).

Публичный API:
  get_web_cookies       →  re-export из app.steam_cookies
  read_steam_cm_app_ids →  определена в этом модуле

Детали аутентификации (TOTP, JWT, keyring) — в app.steam_auth.
Получение веб-кук через браузер  — в app.steam_cookies.
"""

from __future__ import annotations

import logging
import os

# steam использует protobuf 3.x API; при наличии protobuf 4.x нужен python-режим
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

log = logging.getLogger("sam_automation")

# Публичный API модуля
# Внутренние зависимости read_steam_cm_app_ids
from app.auth import (
    _CRED_DIR,
    _USERNAME_FILE,
    _ask_keep_credentials,
    _clear_session,
    _cm_login_with_jwt,
    _compute_steam_totp,
    _do_interactive_login,
    _jwt_from_refresh_token,
    _load_session,
    _load_shared_secret,
    _save_session,
)
from app.cookies import get_web_cookies  # noqa: F401
from app.packageinfo import expand_packages_to_apps


def read_steam_cm_app_ids(
    steam_path: str,
    username: str,
    *,
    interactive: bool = True,
) -> list[int]:
    """Получает App ID всех лицензий аккаунта через Steam CM протокол.

    Args:
        steam_path: путь к папке Steam
        username:   логин Steam аккаунта (из конфига или реестра)
        interactive: разрешить интерактивный ввод пароля/2FA.
                     При False возвращает [] если нет сохранённых данных.

    Returns:
        Список всех App ID которые Steam считает принадлежащими аккаунту.
    """
    try:
        import gevent
        from gevent.event import Event as GEvent
        from steam.client import SteamClient
        from steam.enums import EResult
        from steam.enums.emsg import EMsg
    except ImportError:
        log.warning("Библиотека steam не установлена: pip install steam")
        return []

    client = SteamClient()
    client.set_credential_location(str(_CRED_DIR))

    # Регистрируем слушатель ДО login — иначе race condition
    licenses_event = GEvent()
    client.once(EMsg.ClientLicenseList, lambda _msg: licenses_event.set())

    captured_password: str | None = None
    first_login = False
    want_to_save = False

    _CONNECT_TIMEOUT = 30  # секунд на TCP-подключение к CM-серверу

    def _login_with_timeout(*args, **kwargs):
        """Обёртка над client.login() с таймаутом на фазу подключения."""
        with gevent.Timeout(_CONNECT_TIMEOUT, False):
            return client.login(*args, **kwargs)
        return None  # таймаут истёк

    # Пробуем загрузить сохранённые данные с диска
    saved = _load_session()
    saved_username = (
        saved[0]
        if saved
        else (
            _USERNAME_FILE.read_text(encoding="utf-8").strip()
            if _USERNAME_FILE.exists()
            else None
        )
    )

    # Сначала JWT (без пароля и 2FA) — только CM-токен из refresh_token
    result = None
    if saved_username:
        jwt_cookies = _jwt_from_refresh_token()
        if jwt_cookies:
            access_token = jwt_cookies["steamLoginSecure"].split("||", 1)[1]
            result = _cm_login_with_jwt(
                client, saved_username, access_token, _CONNECT_TIMEOUT
            )
            if result == EResult.OK:
                log.info("Steam CM: вход через JWT (%s)", saved_username)
            else:
                log.debug("Steam CM: JWT не принят (%s), пробую пароль", result)

    if result != EResult.OK and saved:
        saved_username, saved_password = saved
        log.info("Автоматическая авторизация аккаунта Steam под логином %s", saved_username)
        result = _login_with_timeout(saved_username, saved_password)

        if result is None:
            log.warning(
                "Steam CM: таймаут подключения (%ds), удаляю сессию",
                _CONNECT_TIMEOUT,
            )
            _clear_session()
            client.disconnect()
            return []

        # Mobile Authenticator: пароль принят, Steam требует 2FA
        if result == EResult.AccountLoginDeniedNeedTwoFactor:
            shared = _load_shared_secret(saved_username)
            two_factor_code = _compute_steam_totp(shared) if shared else None
            if two_factor_code:
                log.info("Steam CM: 2FA код сгенерирован автоматически")
            else:
                print()
                two_factor_code = input(
                    "[Steam Client Master] Введите 2FA код учётной записи Steam: "
                ).strip()
            result = _login_with_timeout(
                saved_username, saved_password, two_factor_code=two_factor_code
            )

            if result is None:
                log.warning(
                    "Steam CM: таймаут подключения после 2FA (%ds)",
                    _CONNECT_TIMEOUT,
                )
                client.disconnect()
                return []

            # Пароль был верным (иначе 2FA не запросили бы) — не удаляем сессию
            if result != EResult.OK:
                log.warning("Steam CM: неверный 2FA код (%s)", result)
                client.disconnect()
                return []

        elif result == EResult.InvalidPassword:
            log.warning("Steam CM: неверный пароль, удаляю сессию")
            _clear_session()
            saved = None
        elif result != EResult.OK:
            log.warning("Steam CM: вход не удался (%s), удаляю сессию", result)
            _clear_session()
            saved = None

    if not saved and result != EResult.OK:
        if not interactive:
            log.info(
                "Steam CM: нет сохранённых данных, интерактивный режим отключён"
            )
            return []

        first_login = True
        # Спрашиваем ДО логина — чтобы не блокировать event loop после него
        want_to_save = _ask_keep_credentials()
        username = input(
            "[Steam Client Master] Введите логин от учётной записи Steam: "
        ).strip()
        # После неудачного сохранённого входа соединение могло упасть — переподключаемся
        if not client.connected:
            connected = False
            with gevent.Timeout(_CONNECT_TIMEOUT, False):
                connected = client.connect()
            if not connected:
                log.warning(
                    "Steam CM: таймаут подключения к CM-серверу (%ds)",
                    _CONNECT_TIMEOUT,
                )
                return []

        result, username, captured_password = _do_interactive_login(
            client, username
        )

    if result != EResult.OK:
        log.warning("Steam CM: вход не удался: %s", result)
        client.disconnect()
        return []

    # Ждём лицензии
    if not licenses_event.wait(timeout=15):
        log.warning("Steam CM: timeout ожидания списка лицензий")

    owned_packages = set(client.licenses.keys())
    print()

    # Даём event loop время обработать ClientUpdateMachineAuth (sentry)
    client.sleep(3)

    if first_login and want_to_save and captured_password:
        _save_session(client.username or username, captured_password)
        log.info("Данные аккаунта Steam сохранены локально в файл: %s", _USERNAME_FILE)
        log.info("─" * 60)

    log.info("Получение ID приложений библиотеки Steam через Steam Client Master")

    client.disconnect()

    if not owned_packages:
        log.warning("Steam CM: список лицензий пуст")
        return []

    return expand_packages_to_apps(steam_path, owned_packages)
