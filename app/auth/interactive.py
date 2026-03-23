"""Интерактивный вход Steam CM: ввод пароля и кодов 2FA/email."""

from __future__ import annotations

import logging
import sys

from .credentials import _load_shared_secret
from .totp import _compute_steam_totp

log = logging.getLogger("sam_automation")


def _getpass_stars(prompt: str) -> str:
    """Ввод пароля с отображением * вместо символов (Windows)."""
    import msvcrt

    sys.stdout.write(prompt)
    sys.stdout.flush()
    chars: list[str] = []
    while True:
        ch = msvcrt.getwch()
        if ch in ("\r", "\n"):
            sys.stdout.write("\n")
            break
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\x08":  # Backspace
            if chars:
                chars.pop()
                sys.stdout.write("\b \b")
                sys.stdout.flush()
        else:
            chars.append(ch)
            sys.stdout.write("*")
            sys.stdout.flush()
    return "".join(chars)


_LOGIN_TIMEOUT = 60  # секунд на попытку входа


def _do_interactive_login(
    client, username: str
) -> tuple[object, str, str]:
    """Интерактивный логин с захватом логина и пароля.

    Возвращает (result, username, password).
    """

    import gevent
    from steam.enums import EResult

    def _login_timed(*args, **kwargs):
        with gevent.Timeout(_LOGIN_TIMEOUT, False):
            return client.login(*args, **kwargs)
        return None

    def _reconnect_timed():
        if not client.connected:
            client.disconnect()
            with gevent.Timeout(_LOGIN_TIMEOUT, False):
                client.connect()

    password = _getpass_stars(
        "[Steam Client Master] Введите пароль от учётной записи Steam: "
    )
    auth_code = two_factor_code = None
    prompt_for_unavailable = True

    result = _login_timed(username, password)
    if result is None:
        log.warning("Steam CM: таймаут при попытке входа")
        return EResult.Fail, username, password

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
            password = _getpass_stars(
                "[Steam Client Master] Неверный пароль от учётной записи Steam. Введите пароль снова: "
            )
            _reconnect_timed()
        elif result in (
            EResult.AccountLogonDenied,
            EResult.InvalidLoginAuthCode,
        ):
            prompt = (
                "Код из email: "
                if result == EResult.AccountLogonDenied
                else "Неверный код. Введите код из email для учётной записи Steam: "
            )
            auth_code, two_factor_code = input(prompt), None
        elif result in (
            EResult.AccountLoginDeniedNeedTwoFactor,
            EResult.TwoFactorCodeMismatch,
        ):
            shared = _load_shared_secret(username)
            auto_code = _compute_steam_totp(shared) if shared else None
            if auto_code and result == EResult.AccountLoginDeniedNeedTwoFactor:
                log.info("Steam CM: 2FA код сгенерирован автоматически")
                auth_code, two_factor_code = None, auto_code
            else:
                prompt = (
                    "[Steam Client Master] Введите 2FA код учётной записи Steam: "
                    if result == EResult.AccountLoginDeniedNeedTwoFactor
                    else "[Steam Client Master] Неверный код. Введите 2FA код для учётной записи Steam: "
                )
                auth_code, two_factor_code = None, input(prompt)
        elif result in (EResult.TryAnotherCM, EResult.ServiceUnavailable):
            if prompt_for_unavailable and result == EResult.ServiceUnavailable:
                while True:
                    answer = input(
                        "[Steam Client Master] Steam недоступен. Попробовать снова? [yes/no]: "
                    ).lower()
                    if answer in "yesддаnoннет":
                        break
                prompt_for_unavailable = False
                if answer == "n":
                    break
            _reconnect_timed()
            continue

        result = _login_timed(
            username, password, None, auth_code, two_factor_code
        )
        if result is None:
            log.warning("Steam CM: таймаут при попытке входа")
            return EResult.Fail, username, password

    return result, username, password
