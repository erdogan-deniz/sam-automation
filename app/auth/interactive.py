"""Интерактивный вход Steam CM: ввод пароля и кодов 2FA/email."""

from __future__ import annotations

import logging
import sys
from typing import Any

from .credentials import _load_shared_secret
from .iauth_service import _rsa_jwt_login
from .totp import _compute_steam_totp

log = logging.getLogger("sam_automation")


def _getpass_stars(prompt: str) -> str:
    """Запрашивает пароль с отображением * вместо символов (только Windows)."""
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
_MAX_TRANSIENT_TRIES = 3  # предел ре-логинов при транзиентной ошибке CM


def _do_interactive_login(client: Any, username: str) -> tuple[Any, str, str]:
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
    rsa_tried = False
    invalid_pw_tries = 0
    transient_tries = 0

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
            # Legacy ClientLogon отвергает ВЕРНЫЙ пароль для аккаунтов на
            # современном auth → один раз пробуем RSA-путь. Затем для реальной
            # опечатки ограниченно переспрашиваем пароль, НЕ зацикливаясь
            # (иначе modern-auth аккаунт крутит «Неверный пароль» бесконечно).
            if not rsa_tried:
                rsa_tried = True
                rsa_result = _rsa_jwt_login(
                    client, username, password, _LOGIN_TIMEOUT
                )
                if rsa_result == EResult.OK:
                    log.info("Steam CM: вход через RSA/JWT (%s)", username)
                    return EResult.OK, username, password
                log.warning(
                    "Steam CM: RSA-путь не дал входа (%s)",
                    getattr(rsa_result, "name", rsa_result),
                )
            invalid_pw_tries += 1
            if invalid_pw_tries >= 2:
                return EResult.InvalidPassword, username, password
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
                yes = {"y", "yes", "д", "да"}
                no = {"n", "no", "н", "нет"}
                answer = ""
                while answer not in yes and answer not in no:
                    answer = (
                        input(
                            "[Steam Client Master] Steam недоступен. "
                            "Попробовать снова? [yes/no]: "
                        )
                        .strip()
                        .lower()
                    )
                prompt_for_unavailable = False
                if answer in no:
                    break
            # Счётчик транзиентных попыток: без него `result` мог навсегда
            # оставаться TryAnotherCM (login не звался — был `continue`).
            transient_tries += 1
            if transient_tries > _MAX_TRANSIENT_TRIES:
                log.warning(
                    "Steam CM: транзиентная ошибка (%s) не прошла за %d попыток",
                    getattr(result, "name", result),
                    _MAX_TRANSIENT_TRIES,
                )
                break
            _reconnect_timed()
            # НЕ continue: управление доходит до ре-логина ниже, result
            # переприсваивается — иначе вечный цикл на транзиентной ошибке.

        result = _login_timed(
            username, password, None, auth_code, two_factor_code
        )
        if result is None:
            log.warning("Steam CM: таймаут при попытке входа")
            return EResult.Fail, username, password

    return result, username, password
