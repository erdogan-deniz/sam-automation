"""IAuthenticationService: получение JWT через CM (BeginAuth, 2FA, Poll)."""

from __future__ import annotations

import base64
import logging
import urllib.parse
import urllib.request

from ._constants import _CRED_DIR
from .credentials import _load_shared_secret
from .jwt import _jwt_from_refresh_token, _save_jwt_refresh
from .totp import _compute_steam_totp

log = logging.getLogger("sam_automation")


def _jwt_web_cookies(username: str, password: str) -> dict | None:
    """Получает JWT-куки Steam Community через IAuthenticationService (CM протокол).

    Использует новый (2023+) Steam auth API через CM unified messages:
      1. RSA-шифрует пароль (PKCS1_v1.5 с ключом от Steam)
      2. BeginAuthSessionViaCredentials → получает client_id + request_id
      3. Если нужен 2FA/email код — запрашивает у пользователя
      4. PollAuthSessionStatus → access_token (JWT)
      5. Формирует steamLoginSecure = "{steamid}||{access_token}"

    Возвращает dict с JWT-совместимым steamLoginSecure.
    """
    import json

    # ── Попытка восстановить сессию из кэша (без 2FA) ──
    cookies = _jwt_from_refresh_token()
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

        # BeginAuthSessionViaCredentials
        begin = client.send_um_and_wait(
            "Authentication.BeginAuthSessionViaCredentials#1",
            {
                "account_name": username,
                "encrypted_password": enc_pw,
                "encryption_timestamp": ts,
                "remember_login": True,
                "persistence": 1,
                "website_id": "Community",
                "device_friendly_name": "sam-automation",
                "platform_type": 2,  # EAuthTokenPlatformType_SteamClient
                "guard_data": "",
            },
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

        # ── Шаг 4: 2FA / email код если нужен ──
        for conf in b.allowed_confirmations:
            ctype = conf.confirmation_type
            # EAuthSessionGuardType: 2=email, 4=totp, 5=machineToken
            if ctype == 2:
                auto_code = None
                prompt = "\n[Steam JWT] Введи код из email: "
            elif ctype == 4:
                shared = _load_shared_secret(username)
                auto_code = _compute_steam_totp(shared) if shared else None
                if auto_code:
                    log.info("IAuthService: 2FA код сгенерирован автоматически")
                prompt = "\n[Steam JWT] Введи 2FA (TOTP) код: "
            else:
                continue

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
                if er == EResult.OK:
                    accepted = True
                    break
                # eresult=29 (DuplicateRequest) — код уже был принят Steam ранее
                if int(er) == 29:
                    log.debug(
                        "IAuthService: eresult=29 (DuplicateRequest) — продолжаю polling"
                    )
                    accepted = True
                    break
                log.warning(
                    "IAuthService: код отклонён (%s) — введи новый код", er
                )
                prompt = "\n[Steam JWT] Введи свежий код: "

            if not accepted:
                log.warning("IAuthService: код не принят после 3 попыток")
                client.disconnect()
                return None
            break

        # ── Шаг 5: polling до получения токенов ──
        access_token = refresh_token = ""
        for _attempt in range(15):
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
            _save_jwt_refresh(steamid, refresh_token)

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
