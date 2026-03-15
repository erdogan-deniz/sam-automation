"""Получение App ID через Steam CM протокол — по лицензиям аккаунта.

Алгоритм:
  1. Логин в Steam CM (сохранённые данные или интерактивный ввод пароля/2FA)
  2. Получаем список owned пакетов из client.licenses
  3. Разворачиваем пакеты → App ID через локальный packageinfo.vdf
  4. После успешного входа предлагается сохранить данные на диск

Примечание: при сохранении пароль хранится в открытом виде в локальном файле.
"""

from __future__ import annotations

import json
import logging
import os
from getpass import getpass
from pathlib import Path

# steam использует protobuf 3.x API; при наличии protobuf 4.x нужен python-режим
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

log = logging.getLogger("sam_automation")

_CRED_DIR = Path.home() / "AppData" / "Roaming" / "steamctl"
_SESSION_FILE = _CRED_DIR / "steam_helper_session.json"


def _save_session(username: str, password: str) -> None:
    """Сохраняет username+password на диск для следующих запусков."""
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    _SESSION_FILE.write_text(
        json.dumps({"username": username, "password": password}),
        encoding="utf-8",
    )


def _load_session() -> tuple[str, str] | None:
    """Загружает сохранённые данные входа. Возвращает (username, password) или None."""
    if not _SESSION_FILE.exists():
        return None
    try:
        data = json.loads(_SESSION_FILE.read_text(encoding="utf-8"))
        u = data.get("username", "")
        p = data.get("password", "")
        if u and p:
            return u, p
    except Exception:
        pass
    return None


def _clear_session() -> None:
    """Удаляет только файл сессии (пароль). Sentry-файл сохраняется."""
    if _SESSION_FILE.exists():
        _SESSION_FILE.unlink()
        log.info("Steam CM: файл сессии удалён (%s)", _SESSION_FILE)


def _clear_credentials() -> None:
    """Удаляет все данные Steam CM (сессия + sentry)."""
    import shutil
    if _CRED_DIR.exists():
        shutil.rmtree(_CRED_DIR, ignore_errors=True)
        log.info("Steam CM: все данные удалены (%s)", _CRED_DIR)


def _ask_keep_credentials() -> bool:
    """Спрашивает пользователя, сохранить ли данные для следующих запусков."""
    print()
    answer = input(
        "[Steam CM] Сохранить данные входа на диск? "
        "Тогда пароль не нужен при следующем запуске. [y/N]: "
    ).strip().lower()
    return answer in ("y", "yes", "д", "да")


def _do_interactive_login(client, username: str, EResult) -> tuple[object, str]:
    """Интерактивный логин с захватом пароля. Возвращает (result, password)."""
    password = getpass("Password: ")
    auth_code = two_factor_code = None
    prompt_for_unavailable = True

    result = client.login(username, password)

    while result in (
        EResult.AccountLogonDenied,
        EResult.InvalidLoginAuthCode,
        EResult.AccountLoginDeniedNeedTwoFactor,
        EResult.TwoFactorCodeMismatch,
        EResult.TryAnotherCM,
        EResult.ServiceUnavailable,
        EResult.InvalidPassword,
    ):
        client.sleep(0.1)

        if result == EResult.InvalidPassword:
            password = getpass(f"Неверный пароль для {username!r}. Введи пароль: ")
        elif result in (EResult.AccountLogonDenied, EResult.InvalidLoginAuthCode):
            prompt = ("Код из email: " if result == EResult.AccountLogonDenied
                      else "Неверный код. Введи код из email: ")
            auth_code, two_factor_code = input(prompt), None
        elif result in (EResult.AccountLoginDeniedNeedTwoFactor, EResult.TwoFactorCodeMismatch):
            prompt = ("Введи 2FA код: " if result == EResult.AccountLoginDeniedNeedTwoFactor
                      else "Неверный код. Введи 2FA код: ")
            auth_code, two_factor_code = None, input(prompt)
        elif result in (EResult.TryAnotherCM, EResult.ServiceUnavailable):
            if prompt_for_unavailable and result == EResult.ServiceUnavailable:
                while True:
                    answer = input("Steam недоступен. Повторять? [y/n]: ").lower()
                    if answer in "yn":
                        break
                prompt_for_unavailable = False
                if answer == "n":
                    break
            client.reconnect(maxdelay=15)

        result = client.login(username, password, None, auth_code, two_factor_code)

    return result, password


def _expand_packages_to_apps(
    steam_path: str,
    owned_packages: set[int],
) -> list[int]:
    """Разворачивает set пакетов → список App ID через packageinfo.vdf."""
    pkginfo_path = Path(steam_path) / "appcache" / "packageinfo.vdf"
    if not pkginfo_path.exists():
        log.warning("packageinfo.vdf не найден: %s", pkginfo_path)
        return []

    from steam.utils.appcache import parse_packageinfo

    app_ids: list[int] = []
    seen: set[int] = set()
    found_pkgs = 0

    with open(pkginfo_path, "rb") as f:
        _header, pkgs_iter = parse_packageinfo(f)
        for pkg in pkgs_iter:
            pkg_id = pkg.get("packageid")
            if pkg_id not in owned_packages:
                continue
            found_pkgs += 1
            inner = pkg.get("data", {}).get(str(pkg_id), {})
            for app_id in inner.get("appids", {}).values():
                if isinstance(app_id, int) and app_id not in seen:
                    seen.add(app_id)
                    app_ids.append(app_id)

    missing = len(owned_packages) - found_pkgs
    log.info(
        "packageinfo.vdf: %d пакетов найдено из %d лицензий → %d App ID%s",
        found_pkgs,
        len(owned_packages),
        len(app_ids),
        f" (пропущено пакетов: {missing})" if missing else "",
    )
    return app_ids


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
        from steam.client import SteamClient
        from steam.enums import EResult
        from steam.enums.emsg import EMsg
        from gevent.event import Event as GEvent
        import gevent
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
    if saved:
        saved_username, saved_password = saved
        log.info("Steam CM: вход с сохранёнными данными (%s)", saved_username)
        result = _login_with_timeout(saved_username, saved_password)

        if result is None:
            log.warning("Steam CM: таймаут подключения (%ds), удаляю сессию", _CONNECT_TIMEOUT)
            _clear_session()
            client.disconnect()
            return []

        # Mobile Authenticator: пароль принят, Steam требует 2FA
        if result == EResult.AccountLoginDeniedNeedTwoFactor:
            two_factor_code = input("\n[Steam CM] Введи 2FA код: ").strip()
            result = _login_with_timeout(saved_username, saved_password, two_factor_code=two_factor_code)

            if result is None:
                log.warning("Steam CM: таймаут подключения после 2FA (%ds)", _CONNECT_TIMEOUT)
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

    if not saved:
        if not interactive:
            log.info("Steam CM: нет сохранённых данных, интерактивный режим отключён")
            return []

        first_login = True
        # Спрашиваем ДО логина — чтобы не блокировать event loop после него
        want_to_save = _ask_keep_credentials()

        # После неудачного сохранённого входа соединение могло упасть — переподключаемся
        if not client.connected:
            connected = False
            with gevent.Timeout(_CONNECT_TIMEOUT, False):
                connected = client.connect()
            if not connected:
                log.warning("Steam CM: таймаут подключения к CM-серверу (%ds)", _CONNECT_TIMEOUT)
                return []

        log.info("Steam CM: интерактивный вход для %s", username)
        print("\n[Steam CM] Введи пароль и код 2FA для получения полного списка игр.\n")
        result, captured_password = _do_interactive_login(client, username, EResult)

    if result != EResult.OK:
        log.warning("Steam CM: вход не удался: %s", result)
        client.disconnect()
        return []

    # Ждём лицензии
    if not licenses_event.wait(timeout=15):
        log.warning("Steam CM: timeout ожидания списка лицензий")

    owned_packages = set(client.licenses.keys())
    log.info("Steam CM: аккаунт имеет %d пакетов", len(owned_packages))

    # Даём event loop время обработать ClientUpdateMachineAuth (sentry)
    client.sleep(3)

    if first_login and want_to_save and captured_password:
        _save_session(client.username or username, captured_password)
        log.info("Steam CM: данные сохранены (%s)", _SESSION_FILE)

    client.disconnect()

    if not owned_packages:
        log.warning("Steam CM: список лицензий пуст")
        return []

    return _expand_packages_to_apps(steam_path, owned_packages)
