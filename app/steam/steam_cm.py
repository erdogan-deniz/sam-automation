"""Получение App ID через Steam CM протокол — по лицензиям аккаунта.

Алгоритм:
  1. Логин в Steam CM (сохранённые данные или интерактивный ввод пароля/2FA)
  2. Получаем список owned пакетов из client.licenses
  3. Разворачиваем пакеты → App ID через локальный packageinfo.vdf
  4. После успешного входа предлагается сохранить данные на диск

Пароль хранится в Windows Credential Manager через keyring (DPAPI-шифрование).

Публичный API:
  get_web_cookies       →  re-export из app.cookies
  read_steam_cm_app_ids →  определена в этом модуле

Детали аутентификации (TOTP, JWT, keyring) — в app.auth.
Получение веб-кук через браузер  — в app.cookies.
"""

from __future__ import annotations

import logging
import os
import urllib.request

# steam использует protobuf 3.x API; при наличии protobuf 4.x нужен python-режим
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

log = logging.getLogger("sam_automation")

# Лёгкий публичный эндпоинт (без ключа): от доступности Steam WebAPI зависит
# bootstrap списка CM-серверов. Недоступен → вход в CM зависнет/упадёт.
_STEAM_API_PING = (
    "https://api.steampowered.com/ISteamWebAPIUtil/GetServerInfo/v1/"
)


def _steam_api_reachable(timeout: float = 6.0, attempts: int = 2) -> bool:
    """Быстрая проверка доступности Steam WebAPI перед входом в CM.

    Если WebAPI недоступен, интерактивный вход всё равно повиснет уже ПОСЛЕ
    запроса логина/пароля/2FA. Поэтому проверяем заранее и при недоступности
    пропускаем CM, не запрашивая ничего.
    """
    for _ in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(
                _STEAM_API_PING, timeout=timeout
            ) as resp:
                if getattr(resp, "status", 200) == 200:
                    return True
        except Exception:
            continue
    return False


# Транзиентные сетевые ошибки CM (по EResult.name): не проблема пароля —
# повторяем/пропускаем CM, креды НЕ удаляем, в интерактив НЕ падаем.
# TryAnotherCM (48) — именно эта ошибка валила скан.
_TRANSIENT_CM_ERRORS = frozenset(
    {
        "TryAnotherCM",
        "ServiceUnavailable",
        "Timeout",
        "NoConnection",
        "ConnectFailed",
        "RemoteDisconnect",
        "Busy",
    }
)


def _cm_login_outcome(result) -> str:
    """Классифицирует результат входа в CM по EResult.

    Returns:
        "ok"           — вход выполнен
        "bad_password" — неверный пароль: удалить креды, можно интерактив
        "transient"    — сетевая ошибка (TryAnotherCM и пр.): повтор/пропуск,
                         креды сохранить, интерактив НЕ запускать
        "skip"         — прочая ошибка аккаунта (не пароль): пропуск, креды
                         сохранить, интерактив НЕ запускать
    """
    name = getattr(result, "name", str(result))
    if name == "OK":
        return "ok"
    if name == "InvalidPassword":
        return "bad_password"
    if name in _TRANSIENT_CM_ERRORS:
        return "transient"
    return "skip"


def _password_failure_action(result) -> str:
    """Что делать при неуспешном (не OK/None/2FA) логине по сохранённым кредам.

    "try_rsa" — bad_password: legacy ClientLogon мог отвергнуть ВАЛИДНЫЕ креды
                modern-auth аккаунта, поэтому пробуем RSA-путь ДО удаления.
    "skip_cm" — transient/skip: сетевая или ошибка аккаунта (не пароль) —
                креды сохранить, CM пропустить, в интерактив не падать.
    """
    if _cm_login_outcome(result) == "bad_password":
        return "try_rsa"
    return "skip_cm"


def _should_clear_session_after_rsa(rsa_result) -> bool:
    """Стирать ли сохранённые креды после неуспешного RSA/JWT-входа.

    ВСЕГДА False: результат _rsa_jwt_login не даёт надёжного сигнала «неверный
    пароль», а стирание кред необратимо (нарушает инвариант «transient не
    удаляет креды» и виснет в ре-промпте на сетевом сбое).

    Почему ни один исход не оправдывает удаление:
      * None — RSA-этап не выдал токен: это и сетевой сбой (RSA-ключ по HTTP
        или CM недоступны), и отказ поллинга — на месте вызова неразличимо.
      * конкретный EResult приходит из _cm_login_with_jwt, который выполняется
        УЖЕ имея валидный refresh_token (значит пароль был принят) — его неуспех
        транзиентный, CM-сторонний.

    Надёжно отличить настоящий неверный пароль можно лишь tri-state (OK /
    rejected / transient) через весь auth-стек (_jwt_web_cookies →
    _rsa_jwt_login) — оставлено follow-up. До тех пор безопасный дефолт —
    сохранить креды и пропустить CM (скан идёт по localconfig + Steam API).
    """
    return False


# Публичный API модуля
# Внутренние зависимости read_steam_cm_app_ids
# E402 ниже подавлен намеренно: импорты идут после os.environ выше
# (protobuf-режим должен быть выставлен до загрузки библиотеки steam).
from app.auth import (  # noqa: E402
    _CRED_DIR,
    _JWT_REFRESH_CLIENT_FILE,
    _USERNAME_FILE,
    _ask_keep_credentials,
    _clear_session,
    _cm_login_with_jwt,
    _compute_steam_totp,
    _do_interactive_login,
    _load_refresh_token,
    _load_session,
    _load_shared_secret,
    _rsa_jwt_login,
    _save_session,
)
from app.cookies import get_web_cookies  # noqa: F401, E402

from .packageinfo import expand_packages_to_apps  # noqa: E402


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

    # Пре-чек ДО запроса логина/пароля/2FA: если Steam WebAPI недоступен —
    # вход в CM всё равно зависнет. Пропускаем CM (ID уже собраны из
    # localconfig + Steam API), ничего не спрашивая.
    if not _steam_api_reachable():
        log.warning(
            "Steam WebAPI недоступен — пропускаю Steam CM. ID собраны из "
            "localconfig + Steam API; повтори scan позже для лицензий CM."
        )
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

    # Сначала JWT (без пароля и 2FA) — СЫРОЙ SteamClient-scope refresh_token из
    # клиентского кэша (его кладут в ClientLogon.access_token; деривация
    # access_token дала бы пустой/web-токен → AccessDenied).
    result = None
    if saved_username:
        refresh_token = _load_refresh_token(_JWT_REFRESH_CLIENT_FILE)
        if refresh_token:
            result = _cm_login_with_jwt(
                client, saved_username, refresh_token, _CONNECT_TIMEOUT
            )
            if result == EResult.OK:
                log.info("Steam CM: вход через JWT (%s)", saved_username)
            else:
                log.debug("Steam CM: JWT не принят (%s), пробую пароль", result)

    if result != EResult.OK and saved:
        saved_username, saved_password = saved
        log.info(
            "Автоматическая авторизация аккаунта Steam под логином %s",
            saved_username,
        )
        # Транзиентные ошибки CM (TryAnotherCM и пр.) — сетевые, не проблема
        # пароля: пара повторов с переподключением к другому CM-серверу.
        for attempt in range(2):
            result = _login_with_timeout(saved_username, saved_password)
            if result is None or _cm_login_outcome(result) != "transient":
                break
            log.warning(
                "Steam CM: %s — переподключаюсь к другому CM (%d/2)",
                result,
                attempt + 1,
            )
            try:
                client.disconnect()
            except Exception:
                pass
            gevent.sleep(2)

        if result is None:
            # Таймаут подключения — сетевое, креды НЕ трогаем, пропускаем CM.
            log.warning(
                "Steam CM: таймаут подключения (%ds) — пропускаю CM, "
                "учётные данные сохранены",
                _CONNECT_TIMEOUT,
            )
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

        elif result != EResult.OK:
            if _password_failure_action(result) == "try_rsa":
                # InvalidPassword может означать НЕ опечатку, а отказ legacy
                # ClientLogon для modern-auth аккаунта. Пробуем RSA-путь ДО
                # удаления валидных кредов.
                result = _rsa_jwt_login(
                    client, saved_username, saved_password, _CONNECT_TIMEOUT
                )
                if result == EResult.OK:
                    log.info(
                        "Steam CM: вход через RSA/JWT (%s)", saved_username
                    )
                elif _should_clear_session_after_rsa(result):
                    # Зарезервировано под будущий tri-state: удалять сессию ТОЛЬКО
                    # на достоверно-неверном пароле (сейчас недостижимо → no-op).
                    log.warning("Steam CM: неверный пароль, удаляю сессию")
                    _clear_session()
                    saved = None  # → интерактивный ре-ввод ниже
                else:
                    # RSA-провал неотличим от сетевого (см.
                    # _should_clear_session_after_rsa): НЕ стираем валидные
                    # креды — пропускаем CM, скан идёт по localconfig + API.
                    log.warning(
                        "Steam CM: RSA-вход не удался (%s) — пропускаю CM, "
                        "учётные данные сохранены",
                        getattr(result, "name", result),
                    )
                    client.disconnect()
                    return []
            else:
                # Сетевая (transient) или ошибка аккаунта (не пароль): креды
                # сохраняем, в интерактив НЕ падаем, CM пропускаем — скан идёт
                # дальше с ID из localconfig + Steam API.
                log.warning(
                    "Steam CM: вход не удался (%s) — пропускаю CM, "
                    "учётные данные сохранены",
                    getattr(result, "name", result),
                )
                client.disconnect()
                return []

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

        # _do_interactive_login сам пробует RSA-путь на InvalidPassword
        # (legacy ClientLogon отвергает верный пароль для modern-auth аккаунтов).
        result, username, captured_password = _do_interactive_login(
            client, username
        )

    if result != EResult.OK:
        log.warning(
            "Steam CM: вход не удался: %s", getattr(result, "name", result)
        )
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
        log.info(
            "Данные аккаунта Steam сохранены локально в файл: %s",
            _USERNAME_FILE,
        )
        log.info("═" * 80)

    log.info(
        "Получение ID приложений библиотеки Steam через Steam Client Master"
    )

    client.disconnect()

    if not owned_packages:
        log.warning("Steam CM: список лицензий пуст")
        return []

    return expand_packages_to_apps(steam_path, owned_packages)
