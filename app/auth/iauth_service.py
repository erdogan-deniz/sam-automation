"""IAuthenticationService: получение JWT через CM (BeginAuth, 2FA, Poll)."""

from __future__ import annotations

import base64
import logging
import urllib.parse
import urllib.request
from typing import Any

from ._constants import (
    _CRED_DIR,
    _JWT_REFRESH_CLIENT_FILE,
    _JWT_REFRESH_FILE,
)
from .credentials import _load_shared_secret
from .jwt import (
    _cm_login_with_jwt,
    _jwt_from_refresh_token,
    _save_jwt_refresh,
)
from .totp import _compute_steam_totp

log = logging.getLogger("sam_automation")

# EAuthSessionGuardType (проверено по installed proto steammessages_auth_pb2):
#   0 Unknown, 1 None, 2 EmailCode, 3 DeviceCode (TOTP мобильного аутентификатора),
#   4 DeviceConfirmation (подтверждение в приложении, КОДА НЕТ),
#   5 EmailConfirmation (подтверждение по email, кода нет), 6 MachineToken.
_GUARD_EMAIL_CODE = 2
_GUARD_DEVICE_CODE = 3
_GUARD_DEVICE_CONFIRM = 4
_GUARD_EMAIL_CONFIRM = 5


def _guard_action(confirmation_type: int) -> str:
    """Что делать с типом Steam Guard подтверждения (EAuthSessionGuardType).

    Returns:
        "email_code"  — код из email (тип 2): запросить ввод
        "device_code" — TOTP мобильного аутентификатора (тип 3): авто из
                        shared_secret либо ручной ввод
        "confirm"     — подтверждение в приложении/по email (типы 4, 5): КОДА
                        НЕТ, только поллинг (пользователь подтверждает вне утилиты)
        "skip"        — прочее (Unknown/None/MachineToken): нечего вводить
    """
    if confirmation_type == _GUARD_EMAIL_CODE:
        return "email_code"
    if confirmation_type == _GUARD_DEVICE_CODE:
        return "device_code"
    if confirmation_type in (_GUARD_DEVICE_CONFIRM, _GUARD_EMAIL_CONFIRM):
        return "confirm"
    return "skip"


def _jwt_web_cookies(
    username: str, password: str, *, for_steam_client: bool = False
) -> dict | None:
    """Получает JWT-токен через IAuthenticationService (CM unified messages).

    Использует новый (2023+) Steam auth API:
      1. RSA-шифрует пароль (PKCS1_v1.5 с ключом от Steam)
      2. BeginAuthSessionViaCredentials → получает client_id + request_id
      3. Если нужен 2FA/email код — запрашивает у пользователя
      4. PollAuthSessionStatus → access_token (JWT)
      5. Формирует steamLoginSecure = "{steamid}||{access_token}"

    for_steam_client=True выпускает токен с platform_type=SteamClient (для логона
    в CM); иначе WebBrowser-scope (для веб-кук). Это РАЗНЫЕ scope — кэшируются в
    разные файлы, иначе CM-логон даёт AccessDenied на веб-токене.

    Возвращает dict с JWT-совместимым steamLoginSecure.
    """
    import json

    cache_file = (
        _JWT_REFRESH_CLIENT_FILE if for_steam_client else _JWT_REFRESH_FILE
    )

    # ── Попытка восстановить сессию из кэша (без 2FA) ──
    cookies = _jwt_from_refresh_token(cache_file)
    if cookies:
        return cookies

    # ── Шаг 1: RSA ключ для шифрования пароля (HTTP, работает без CM) ──
    try:
        url = (
            "https://api.steampowered.com/IAuthenticationService"
            f"/GetPasswordRSAPublicKey/v1?account_name={urllib.parse.quote(username)}"
        )
        with urllib.request.urlopen(url, timeout=15) as r:
            rsa_resp = json.loads(r.read())["response"]
        mod = int(rsa_resp["publickey_mod"], 16)
        exp = int(rsa_resp["publickey_exp"], 16)
        ts = int(rsa_resp["timestamp"])
    except Exception as e:
        log.warning("IAuthService: RSA ключ не получен: %s", e)
        return None

    # ── Шаг 2: RSA-PKCS1_v1.5 шифрование пароля ──
    try:
        from Cryptodome.Cipher import PKCS1_v1_5
        from Cryptodome.PublicKey.RSA import construct as rsa_construct

        rsa_key = rsa_construct((mod, exp))
        enc_pw = base64.b64encode(
            PKCS1_v1_5.new(rsa_key).encrypt(password.encode())
        ).decode()
    except Exception as e:
        log.warning("IAuthService: RSA шифрование не удалось: %s", e)
        return None

    # ── Шаг 3: BeginAuthSessionViaCredentials через CM unified messages ──
    try:
        from steam.client import SteamClient
        from steam.enums import EResult
    except ImportError:
        log.warning("IAuthService: steam библиотека недоступна")
        return None

    client = SteamClient()
    client.set_credential_location(str(_CRED_DIR))

    try:
        import gevent

        connected = False
        with gevent.Timeout(20, False):
            connected = client.connect()
        if not connected:
            log.warning("IAuthService: не удалось подключиться к CM серверу")
            return None

        # Анонимный логин нужен чтобы CM принял unified messages
        result = client.anonymous_login()
        if result != EResult.OK:
            log.warning("IAuthService: anonymous_login не удался: %s", result)
            client.disconnect()
            return None

        # BeginAuthSessionViaCredentials. Scope токена определяется platform_type:
        #   SteamClient(1) → токен валиден для логона в CM (ClientLogon)
        #   WebBrowser(2)  → токен для веб-кук (steamLoginSecure)
        # Для SteamClient передаётся device_details, website_id не нужен.
        begin_params: dict = {
            "account_name": username,
            "encrypted_password": enc_pw,
            "encryption_timestamp": ts,
            "remember_login": True,
            "persistence": 1,
            "guard_data": "",
        }
        if for_steam_client:
            begin_params["platform_type"] = 1  # SteamClient
            begin_params["device_details"] = {
                "device_friendly_name": "sam-automation",
                "platform_type": 1,  # SteamClient
                "os_type": 16,  # EOSType.Windows10
            }
        else:
            begin_params["platform_type"] = 2  # WebBrowser
            begin_params["website_id"] = "Community"
            begin_params["device_friendly_name"] = "sam-automation"

        begin = client.send_um_and_wait(
            "Authentication.BeginAuthSessionViaCredentials#1",
            begin_params,
            timeout=15,
        )

        if begin is None:
            log.warning(
                "IAuthService: BeginAuthSessionViaCredentials: нет ответа"
            )
            client.disconnect()
            return None

        if begin.header.eresult != EResult.OK:
            log.warning(
                "IAuthService: BeginAuthSessionViaCredentials ошибка: %s (%s)",
                begin.header.eresult,
                begin.header.error_message,
            )
            client.disconnect()
            return None

        b = begin.body
        client_id = b.client_id
        request_id = b.request_id
        steamid = str(b.steamid)
        interval = max(b.interval or 5.0, 1.0)

        # ── Шаг 4: Steam Guard (2FA) по типам allowed_confirmations ──
        # _guard_action различает код (email/TOTP) и внешнее подтверждение
        # (в приложении/по email — кода нет, только ждём поллингом).
        actions = {
            _guard_action(c.confirmation_type): c.confirmation_type
            for c in b.allowed_confirmations
        }
        needs_confirm = False
        ctype = None
        if "device_code" in actions:  # TOTP — можем сгенерировать сами
            ctype = actions["device_code"]
        elif "email_code" in actions:
            ctype = actions["email_code"]
        elif "confirm" in actions:
            needs_confirm = True

        if ctype is not None:
            if _guard_action(ctype) == "device_code":
                shared = _load_shared_secret(username)
                auto_code = _compute_steam_totp(shared) if shared else None
                if auto_code:
                    log.info("IAuthService: 2FA код сгенерирован автоматически")
                prompt = (
                    "\n[Steam JWT] Введи код Steam Guard "
                    "(мобильный аутентификатор): "
                )
            else:
                auto_code = None
                prompt = "\n[Steam JWT] Введи код из email: "

            accepted = False
            for _try in range(3):
                code = (
                    auto_code
                    if (auto_code and _try == 0)
                    else input(prompt).strip()
                )
                auto_code = None  # следующие попытки — только ручной ввод
                upd = client.send_um_and_wait(
                    "Authentication.UpdateAuthSessionWithSteamGuardCode#1",
                    {
                        "client_id": client_id,
                        "steamid": int(steamid),
                        "code": code,
                        "code_type": ctype,
                    },
                    timeout=15,
                )
                if upd is None:
                    log.warning(
                        "IAuthService: нет ответа от сервера, пробую снова"
                    )
                    continue
                er = upd.header.eresult
                # eresult=29 (DuplicateRequest) — код уже принят Steam ранее
                if er == EResult.OK or int(er) == 29:
                    accepted = True
                    break
                log.warning(
                    "IAuthService: код отклонён (%s) — введи новый код",
                    getattr(er, "name", er),
                )
                prompt = "\n[Steam JWT] Введи свежий код: "

            if not accepted:
                log.warning("IAuthService: код не принят после 3 попыток")
                client.disconnect()
                return None
        elif needs_confirm:
            log.info(
                "IAuthService: подтверди вход в приложении Steam Mobile "
                "(или по ссылке из email) — ожидаю подтверждения..."
            )

        # ── Шаг 5: polling до получения токенов ──
        # Внешнее подтверждение требует времени на действие пользователя —
        # даём более длинное окно поллинга.
        poll_attempts = 30 if needs_confirm else 15
        access_token = refresh_token = ""
        for _attempt in range(poll_attempts):
            client.sleep(interval)
            poll = client.send_um_and_wait(
                "Authentication.PollAuthSessionStatus#1",
                {"client_id": client_id, "request_id": request_id},
                timeout=15,
            )
            if poll is None:
                continue
            if poll.header.eresult != EResult.OK:
                log.debug("IAuthService: poll eresult=%s", poll.header.eresult)
                break
            p = poll.body
            if p.access_token:
                access_token = p.access_token
                refresh_token = p.refresh_token or ""
                break
            if p.had_remote_interaction:
                log.info("IAuthService: ожидаю подтверждения в Steam Mobile...")

        client.disconnect()

        if not access_token or not steamid:
            log.warning("IAuthService: токены не получены")
            return None

        if refresh_token:
            _save_jwt_refresh(steamid, refresh_token, cache_file)

        cookie_val = f"{steamid}||{access_token}"
        log.info("IAuthService: JWT получен для steamid=%s", steamid)
        return {"steamLoginSecure": cookie_val}

    except Exception as e:
        log.warning("IAuthService: ошибка: %s", e)
        try:
            client.disconnect()
        except Exception:
            pass
        return None


def _rsa_jwt_login(
    client: Any, username: str, password: str, connect_timeout: int
) -> Any:
    """Современный RSA-путь входа в CM: пароль → JWT access_token → CM-логин.

    Для аккаунтов, переведённых Steam на современный auth, legacy
    client.login(пароль) возвращает InvalidPassword даже на ВЕРНОМ пароле.
    Здесь пароль идёт через BeginAuthSessionViaCredentials (RSA), а полученный
    access_token предъявляется в ClientLogon.

    Returns:
        EResult входа в CM (OK при успехе) либо None, если RSA-этап не дал
        токена (неверный пароль/2FA/сетевая ошибка — см. логи _jwt_web_cookies).
    """
    # for_steam_client=True: токен SteamClient-scope, иначе CM даёт AccessDenied.
    cookies = _jwt_web_cookies(username, password, for_steam_client=True)
    if not cookies:
        return None
    access_token = cookies["steamLoginSecure"].split("||", 1)[1]
    # Неудачный legacy-вход роняет CM-соединение; _cm_login_with_jwt
    # переподключится сам — снимаем возможное полуоткрытое состояние.
    try:
        client.disconnect()
    except Exception:
        pass
    return _cm_login_with_jwt(client, username, access_token, connect_timeout)
