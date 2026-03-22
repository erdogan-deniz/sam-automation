"""Получение App ID через Steam CM протокол — по лицензиям аккаунта.

Алгоритм:
  1. Логин в Steam CM (сохранённые данные или интерактивный ввод пароля/2FA)
  2. Получаем список owned пакетов из client.licenses
  3. Разворачиваем пакеты → App ID через локальный packageinfo.vdf
  4. После успешного входа предлагается сохранить данные на диск

Пароль хранится в Windows Credential Manager через keyring (DPAPI-шифрование).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from getpass import getpass
from pathlib import Path

import keyring
import keyring.errors

# steam использует protobuf 3.x API; при наличии protobuf 4.x нужен python-режим
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

log = logging.getLogger("sam_automation")

_CRED_DIR = Path.home() / "AppData" / "Roaming" / "steamctl"
# Хранит только имя пользователя — пароль идёт в Credential Manager
_USERNAME_FILE = _CRED_DIR / "username.txt"
# Ручной cookie — пользователь вставляет значение steamLoginSecure из браузера
_MANUAL_COOKIE_FILE = _CRED_DIR / "manual_cookie.txt"
# Старый файл — нужен для однократной миграции
_LEGACY_SESSION_FILE = _CRED_DIR / "steam_helper_session.json"
_KEYRING_SERVICE = "sam-automation"
_KEYRING_2FA_SERVICE = "sam-automation-2fa"
# Кэш JWT refresh-токена для повторного получения access_token без 2FA
_JWT_REFRESH_FILE = _CRED_DIR / "jwt_refresh.json"
# steamRememberLogin — долгоживущий web-токен для обновления сессии без перелогина
_REMEMBER_LOGIN_FILE = _CRED_DIR / "remember_login.txt"


def _compute_steam_totp(shared_secret: str) -> str:
    """Вычисляет Steam Guard TOTP-код из shared_secret.

    Алгоритм: HMAC-SHA1(base64(shared_secret), floor(time/30) как big-endian uint64).
    Алфавит Steam: 23456789BCDFGHJKMNPQRTVWXY (25 символов, 5 символов кода).
    """
    import hashlib
    import hmac
    import struct

    secret = base64.b64decode(shared_secret)
    msg = struct.pack(">Q", int(time.time()) // 30)
    mac = hmac.new(secret, msg, hashlib.sha1).digest()
    start = mac[19] & 0xF
    code_int = struct.unpack(">I", mac[start : start + 4])[0] & 0x7FFFFFFF
    chars = "23456789BCDFGHJKMNPQRTVWXY"
    code = ""
    for _ in range(5):
        code_int, i = divmod(code_int, len(chars))
        code = chars[i] + code
    return code


def _load_shared_secret(username: str) -> str | None:
    """Загружает Steam Guard shared_secret из keyring или SDA maFile."""
    # 1. Keyring (Windows Credential Manager — DPAPI-шифрование)
    try:
        secret = keyring.get_password(_KEYRING_2FA_SERVICE, username)
        if secret:
            return secret
    except Exception:
        pass

    # 2. SteamDesktopAuthenticator maFiles (если SDA установлен)
    sda_dir = Path.home() / "AppData" / "Roaming" / "SteamDesktopAuthenticator" / "maFiles"
    if sda_dir.exists():
        for maf in sda_dir.glob("*.maFile"):
            try:
                data = json.loads(maf.read_text(encoding="utf-8"))
                if data.get("account_name", "").lower() != username.lower():
                    continue
                secret = data.get("shared_secret", "")
                if secret:
                    log.info("Найден SDA maFile: %s", maf.name)
                    return secret
            except Exception:
                pass

    return None


def _save_shared_secret(username: str, secret: str) -> None:
    """Сохраняет shared_secret в Windows Credential Manager."""
    keyring.set_password(_KEYRING_2FA_SERVICE, username, secret)
    log.info("shared_secret сохранён в Credential Manager")


def _save_session(username: str, password: str) -> None:
    """Сохраняет username на диск, пароль — в Windows Credential Manager."""
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    _USERNAME_FILE.write_text(username, encoding="utf-8")
    keyring.set_password(_KEYRING_SERVICE, username, password)


def _load_session() -> tuple[str, str] | None:
    """Загружает сохранённые данные входа. Возвращает (username, password) или None.

    При наличии старого JSON-файла автоматически мигрирует в Credential Manager.
    """
    # Однократная миграция: старый plaintext JSON → keyring
    if _LEGACY_SESSION_FILE.exists():
        try:
            data = json.loads(_LEGACY_SESSION_FILE.read_text(encoding="utf-8"))
            u = data.get("username", "")
            p = data.get("password", "")
            if u and p:
                _save_session(u, p)
                _LEGACY_SESSION_FILE.unlink()
                log.info("Steam CM: учётные данные перенесены в Credential Manager")
                return u, p
        except Exception:
            pass
        _LEGACY_SESSION_FILE.unlink(missing_ok=True)

    if not _USERNAME_FILE.exists():
        return None
    username = _USERNAME_FILE.read_text(encoding="utf-8").strip()
    if not username:
        return None
    try:
        password = keyring.get_password(_KEYRING_SERVICE, username)
    except Exception:
        return None
    return (username, password) if password else None


def _clear_session() -> None:
    """Удаляет пароль из Credential Manager и username-файл. Sentry сохраняется."""
    if _USERNAME_FILE.exists():
        username = _USERNAME_FILE.read_text(encoding="utf-8").strip()
        if username:
            try:
                keyring.delete_password(_KEYRING_SERVICE, username)
            except keyring.errors.PasswordDeleteError:
                pass
        _USERNAME_FILE.unlink()
        log.info("Steam CM: учётные данные удалены из Credential Manager")


def _clear_credentials() -> None:
    """Удаляет все данные Steam CM (сессия + sentry)."""
    import shutil
    _clear_session()
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


def _cm_login_with_jwt(client, username: str, access_token: str, connect_timeout: int):
    """Логинится в Steam CM используя JWT access_token (без пароля и 2FA)."""
    import gevent
    from steam.core.msg import MsgProto
    from steam.enums.emsg import EMsg
    from steam.enums import EResult
    from gevent.event import Event as GEvent

    connected = False
    with gevent.Timeout(connect_timeout, False):
        connected = client.connect()
    if not connected:
        return None

    auth_event = GEvent()
    result_holder = [None]

    def on_logon(msg):
        result_holder[0] = EResult(msg.body.eresult)
        auth_event.set()

    client.once(EMsg.ClientLogOnResponse, on_logon)

    msg = MsgProto(EMsg.ClientLogon)
    msg.body.account_name = username
    msg.body.access_token = access_token
    msg.body.protocol_version = 65580
    client.send(msg)

    auth_event.wait(timeout=30)
    result = result_holder[0]

    if result != EResult.OK:
        client.disconnect()

    return result


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
            shared = _load_shared_secret(username)
            auto_code = _compute_steam_totp(shared) if shared else None
            if auto_code and result == EResult.AccountLoginDeniedNeedTwoFactor:
                log.info("Steam CM: 2FA код сгенерирован автоматически")
                auth_code, two_factor_code = None, auto_code
            else:
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
            continue

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


def _save_jwt_refresh(steamid: str, refresh_token: str) -> None:
    """Сохраняет JWT refresh-токен на диск для повторного использования без 2FA."""
    import json
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    _JWT_REFRESH_FILE.write_text(
        json.dumps({"steamid": steamid, "refresh_token": refresh_token}),
        encoding="utf-8",
    )
    log.debug("IAuthService: refresh_token сохранён")


def _jwt_from_refresh_token() -> dict | None:
    """Пробует получить новый access_token из кэшированного refresh_token.

    Не требует 2FA. Возвращает None если кэш пуст или токен истёк.
    """
    import json

    if not _JWT_REFRESH_FILE.exists():
        return None

    try:
        data = json.loads(_JWT_REFRESH_FILE.read_text(encoding="utf-8"))
        steamid = data.get("steamid", "")
        refresh_token = data.get("refresh_token", "")
        if not steamid or not refresh_token:
            return None
    except Exception:
        return None

    try:
        from steam.client import SteamClient
        from steam.enums import EResult
        import gevent

        client = SteamClient()
        try:
            connected = False
            with gevent.Timeout(20, False):
                connected = client.connect()
            if not connected:
                return None

            result = client.anonymous_login()
            if result != EResult.OK:
                client.disconnect()
                return None

            resp = client.send_um_and_wait(
                "Authentication.GenerateAccessTokenForApp#1",
                {"refresh_token": refresh_token, "steamid": int(steamid)},
                timeout=15,
            )
            client.disconnect()

            if resp is None or resp.header.eresult != EResult.OK:
                log.debug("IAuthService: refresh_token истёк или недействителен")
                _JWT_REFRESH_FILE.unlink(missing_ok=True)
                return None

            access_token = resp.body.access_token
            if not access_token:
                _JWT_REFRESH_FILE.unlink(missing_ok=True)
                return None

            log.info("IAuthService: JWT обновлён через refresh_token (без 2FA)")
            return {"steamLoginSecure": f"{steamid}||{access_token}"}

        except Exception as e:
            log.debug("IAuthService: refresh_token ошибка: %s", e)
            try:
                client.disconnect()
            except Exception:
                pass
            return None
    except ImportError:
        return None


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
    import base64
    import json
    import urllib.parse
    import urllib.request

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
        from Cryptodome.PublicKey.RSA import construct as rsa_construct
        from Cryptodome.Cipher import PKCS1_v1_5
        rsa_key = rsa_construct((mod, exp))
        enc_pw = base64.b64encode(PKCS1_v1_5.new(rsa_key).encrypt(password.encode())).decode()
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
            log.warning("IAuthService: BeginAuthSessionViaCredentials: нет ответа")
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
                code = auto_code if (auto_code and _try == 0) else input(prompt).strip()
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
                    log.warning("IAuthService: нет ответа от сервера, пробую снова")
                    continue
                er = upd.header.eresult
                if er == EResult.OK:
                    accepted = True
                    break
                # eresult=29 (DuplicateRequest) — код уже был принят Steam ранее
                # (библиотека могла отправить запрос дважды). Продолжаем polling.
                if int(er) == 29:
                    log.debug("IAuthService: eresult=29 (DuplicateRequest) — продолжаю polling")
                    accepted = True
                    break
                log.warning("IAuthService: код отклонён (%s) — введи новый код", er)
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

        # Кэшируем refresh_token для будущих запусков (без 2FA)
        if refresh_token:
            _save_jwt_refresh(steamid, refresh_token)

        # steamLoginSecure = "{steamid64}||{jwt_access_token}"
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


def _web_auth_cookies(username: str, password: str) -> dict | None:
    """Получает куки Steam Community через HTTP WebAuth (запасной путь если CM nonce недоступен).

    Использует старый endpoint login/dologin — может не работать для новых аккаунтов
    с обязательным IAuthenticationService. В этом случае вернёт None.
    """
    try:
        from steam.webauth import WebAuth, TwoFactorCodeRequired, LoginIncorrect
    except ImportError:
        return None

    log.info("WebAuth: пробую HTTP-логин через steamcommunity.com/login/dologin/...")
    try:
        wa = WebAuth(username, password)
        try:
            wa.login()
        except TwoFactorCodeRequired:
            code = input("\n[WebAuth] Введи 2FA код: ").strip()
            try:
                wa.login(twofactor_code=code)
            except KeyError as e:
                # Steam убрал поле transfer_parameters из ответа, но куки уже установлены
                log.debug("WebAuth: _finalize_login упал на отсутствующем поле %s (ожидаемо)", e)
        except KeyError as e:
            log.debug("WebAuth: _finalize_login упал на отсутствующем поле %s (ожидаемо)", e)
    except LoginIncorrect as e:
        log.warning("WebAuth: неверный логин/пароль: %s", e)
        return None
    except Exception as e:
        log.warning("WebAuth: ошибка: %s", e)
        return None

    cookies = {
        c.name: c.value
        for c in wa.session.cookies
        if c.domain in ("steamcommunity.com", ".steamcommunity.com")
    }
    if cookies:
        log.info("WebAuth: куки получены: %s", list(cookies.keys()))
        return cookies

    log.warning("WebAuth: cookies пусты — возможно, Steam отклонил старый login flow")
    return None


def _dpapi_decrypt(data: bytes) -> bytes | None:
    """Расшифровывает DPAPI-защищённые данные через ctypes (без win32crypt)."""
    import ctypes
    import ctypes.wintypes

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = _DataBlob(len(data), buf)
    blob_out = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    )
    if not ok:
        return None
    result = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return result


def _decrypt_chrome_value(encrypted_value: bytes, key: bytes) -> str | None:
    """Расшифровывает значение куки Chrome.

    v10 = AES-256-GCM (Chrome < 127) — требует пакет cryptography.
    v20 = App-Bound Encryption (Chrome 127+) — невозможно без Chrome.
    Без префикса = старый DPAPI напрямую.
    """
    if not encrypted_value:
        return None

    prefix = encrypted_value[:3]

    if prefix == b"v10":
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            log.debug("cryptography не установлен — Chrome v10 cookies пропущены")
            return None
        try:
            nonce = encrypted_value[3:15]
            ciphertext = encrypted_value[15:]
            return AESGCM(key).decrypt(nonce, ciphertext, None).decode("utf-8")
        except Exception:
            return None

    if prefix == b"v20":
        # App-Bound Encryption (Chrome 127+) — пропускаем
        return None

    # Старый формат: DPAPI без AES обёртки
    try:
        result = _dpapi_decrypt(encrypted_value)
        return result.decode("utf-8") if result else None
    except Exception:
        return None


def _firefox_steam_cookies() -> dict | None:
    """Читает Steam Community куки напрямую из SQLite Firefox.

    Firefox не шифрует куки на уровне ОС — они хранятся открытым текстом.
    """
    import shutil
    import sqlite3
    import tempfile

    profiles_dir = (
        Path.home() / "AppData" / "Roaming" / "Mozilla" / "Firefox" / "Profiles"
    )
    if not profiles_dir.exists():
        return None

    for profile in profiles_dir.iterdir():
        cookies_db = profile / "cookies.sqlite"
        if not cookies_db.exists():
            continue

        # Firefox блокирует файл во время работы — копируем во временную папку
        # (вместе с WAL-файлом, иначе пропустим незакоммиченные транзакции)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_db = Path(tmpdir) / "cookies.sqlite"
            try:
                shutil.copy2(cookies_db, tmp_db)
                for ext in ("-wal", "-shm"):
                    src = Path(str(cookies_db) + ext)
                    if src.exists():
                        shutil.copy2(src, Path(tmpdir) / ("cookies.sqlite" + ext))
                conn = sqlite3.connect(tmp_db)
                try:
                    cur = conn.execute(
                        "SELECT name, value FROM moz_cookies "
                        "WHERE host LIKE '%steamcommunity.com' AND expiry > strftime('%s','now')"
                    )
                    cookies = {row[0]: row[1] for row in cur}
                finally:
                    conn.close()
            except Exception as e:
                log.debug("Firefox cookies (%s): %s", profile.name, e)
                cookies = {}

        if cookies.get("steamLoginSecure"):
            log.info(
                "Firefox cookies: профиль %s (%s)", profile.name, list(cookies.keys())
            )
            return cookies

    return None


def _copy_shared(src: Path, dst: Path) -> None:
    """Копирует файл с явными флагами FILE_SHARE_READ|WRITE|DELETE.

    Работает даже когда браузер держит файл открытым (SQLite byte-range locking).
    Падает с OSError если файл открыт с эксклюзивным доступом без sharing.
    """
    import ctypes
    import ctypes.wintypes as wt

    GENERIC_READ = 0x80000000
    FILE_SHARE_ALL = 0x7          # READ | WRITE | DELETE
    OPEN_EXISTING = 3
    INVALID_HANDLE = wt.HANDLE(-1).value

    k32 = ctypes.windll.kernel32
    # Без явного restype ctypes возвращает c_int (32-бит) — HANDLE на 64-бит Windows
    # может быть шире, тогда дескриптор будет обрезан и GetFileSizeEx упадёт.
    k32.CreateFileW.restype = wt.HANDLE
    k32.GetFileSizeEx.restype = wt.BOOL
    k32.ReadFile.restype = wt.BOOL

    h = k32.CreateFileW(str(src), GENERIC_READ, FILE_SHARE_ALL, None, OPEN_EXISTING, 0, None)
    if h == INVALID_HANDLE:
        err = k32.GetLastError()
        raise OSError(err, f"CreateFileW failed (err={err}): {src}")
    try:
        # stat().st_size возвращает 0 для открытых файлов — используем GetFileSizeEx
        class _LargeInt(ctypes.Structure):
            _fields_ = [("QuadPart", ctypes.c_int64)]

        li = _LargeInt()
        if not k32.GetFileSizeEx(h, ctypes.byref(li)):
            raise OSError(k32.GetLastError(), f"GetFileSizeEx failed: {src}")
        size = li.QuadPart
        buf = ctypes.create_string_buffer(size)
        read = wt.DWORD()
        k32.ReadFile(h, buf, size, ctypes.byref(read), None)
        dst.write_bytes(bytes(buf)[: read.value])
    finally:
        k32.CloseHandle(h)


def _chrome_steam_cookies() -> dict | None:
    """Читает Steam Community куки из Chrome/Edge/Brave через DPAPI + AES-GCM.

    Работает для v10 куки (Chrome < 127). Chrome 127+ использует App-Bound
    Encryption (v20) — такие куки пропускаются.
    """
    import base64
    import json
    import shutil
    import sqlite3
    import tempfile

    # Используем браузер по умолчанию первым, затем остальные
    default_channel, _default_exe, default_profile = _default_browser()
    default_profile_path = Path(default_profile) if default_profile else None

    all_profile_dirs = [
        # Steam-клиент (CEF Chromium) — всегда доступен если Steam запущен, не заблокирован
        Path.home() / "AppData" / "Local" / "Steam" / "htmlcache",
        Path.home() / "AppData" / "Local" / "Yandex" / "YandexBrowser" / "User Data",
        Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data",
        Path.home() / "AppData" / "Local" / "BraveSoftware" / "Brave-Browser" / "User Data",
        Path.home() / "AppData" / "Local" / "Microsoft" / "Edge" / "User Data",
        Path.home() / "AppData" / "Local" / "Vivaldi" / "User Data",
    ]
    # Браузер по умолчанию — первым
    if default_profile_path and default_profile_path not in all_profile_dirs:
        all_profile_dirs.insert(0, default_profile_path)
    elif default_profile_path and default_profile_path in all_profile_dirs:
        all_profile_dirs.remove(default_profile_path)
        all_profile_dirs.insert(0, default_profile_path)

    browser_dirs = all_profile_dirs

    for user_data in browser_dirs:
        local_state = user_data / "Local State"
        if not local_state.exists():
            continue

        # Расшифровываем AES-ключ из Local State через DPAPI
        try:
            state = json.loads(local_state.read_text(encoding="utf-8"))
            enc_key_b64 = state.get("os_crypt", {}).get("encrypted_key", "")
            if not enc_key_b64:
                continue
            enc_key = base64.b64decode(enc_key_b64)
            if enc_key[:5] == b"DPAPI":
                enc_key = enc_key[5:]
            key = _dpapi_decrypt(enc_key)
            if not key:
                continue
        except Exception as e:
            log.debug("Chrome key (%s): %s", user_data.name, e)
            continue

        for profile in (".", "Default", "Profile 1", "Profile 2"):
            for rel in (
                Path(profile) / "Network" / "Cookies",
                Path(profile) / "Cookies",
            ):
                cookies_path = user_data / rel
                if not cookies_path.exists():
                    continue

                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp_db = Path(tmpdir) / "Cookies"
                    try:
                        _copy_shared(cookies_path, tmp_db)
                        for ext in ("-wal", "-shm"):
                            src = Path(str(cookies_path) + ext)
                            if src.exists():
                                _copy_shared(src, Path(tmpdir) / ("Cookies" + ext))
                        conn = sqlite3.connect(tmp_db)
                        try:
                            cur = conn.execute(
                                "SELECT name, encrypted_value FROM cookies "
                                "WHERE (host_key LIKE '%steamcommunity.com' OR host_key LIKE '%steam.tv')"
                                " AND expires_utc > 0"
                            )
                            cookies = {}
                            for name, enc_val in cur:
                                val = _decrypt_chrome_value(bytes(enc_val), key)
                                if val:
                                    cookies[name] = val
                        finally:
                            conn.close()
                    except Exception as e:
                        log.debug("Chrome cookies (%s/%s): %s", user_data.name, profile, e)
                        cookies = {}

                if cookies.get("steamLoginSecure"):
                    log.info(
                        "Chrome cookies: %s/%s (%s)",
                        user_data.name, profile, list(cookies.keys()),
                    )
                    return cookies

    return None


# Chromium-based браузеры: ключ = подстрока ProgId, значение = (channel, profile_rel_path)
# channel=None → браузер не является системным каналом Playwright; exe читается из реестра
_BROWSER_DEFS: dict[str, tuple[str | None, str]] = {
    "chrome":  ("chrome",  "AppData/Local/Google/Chrome/User Data"),
    "msedge":  ("msedge",  "AppData/Local/Microsoft/Edge/User Data"),
    "edge":    ("msedge",  "AppData/Local/Microsoft/Edge/User Data"),
    "yandex":  (None,      "AppData/Local/Yandex/YandexBrowser/User Data"),
    "brave":   (None,      "AppData/Local/BraveSoftware/Brave-Browser/User Data"),
    "opera":   (None,      "AppData/Roaming/Opera Software/Opera Stable"),
    "vivaldi": (None,      "AppData/Local/Vivaldi/User Data"),
}


def _default_browser() -> tuple[str | None, str | None, str | None]:
    """Возвращает (channel, exe_path, profile_path) для браузера по умолчанию.

    Читает ProgId из HKCU\\...\\UrlAssociations\\http\\UserChoice.
    Путь к exe берётся из реестра (SOFTWARE\\Classes\\{ProgId}\\shell\\open\\command),
    а не хардкодится — работает для любой версии и пути установки.
    """
    import re
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        ) as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0]

        prog_id_lower = prog_id.lower()

        # Ищем браузер в нашем словаре
        channel, profile = None, None
        for keyword, (ch, profile_rel) in _BROWSER_DEFS.items():
            if keyword in prog_id_lower:
                channel = ch
                profile = str(Path.home() / profile_rel)
                break

        # Для не-channel браузеров читаем путь к exe из реестра
        exe = None
        if channel is None:
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    sub = rf"SOFTWARE\Classes\{prog_id}\shell\open\command"
                    with winreg.OpenKey(root, sub) as k:
                        cmd = winreg.QueryValueEx(k, "")[0]
                        m = re.match(r'"([^"]+\.exe)"', cmd)
                        if m:
                            exe = m.group(1)
                            break
                except Exception:
                    pass

        return channel, exe, profile

    except Exception:
        pass
    return None, None, None


def _playwright_steam_cookies(*, visible_fallback: bool = True) -> dict | None:
    """Извлекает Steam JWT cookies через Playwright.

    Шаг 1: пробует профиль браузера по умолчанию (тихо, без окна).
    Шаг 2 (только если visible_fallback=True): открывает видимое окно для входа.
    Playwright использует CDP → читает HttpOnly cookies напрямую,
    минуя v20-шифрование SQLite-файла Chrome/Edge.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.debug("playwright не установлен (pip install playwright)")
        return None

    def _launch_kwargs(channel: str | None, exe: str | None) -> dict:
        """Формирует kwargs для pw.chromium.launch[_persistent_context]."""
        if channel:
            return {"channel": channel}
        if exe and Path(exe).exists():
            return {"executable_path": exe}
        return {}  # встроенный Playwright Chromium

    # Браузер по умолчанию — первым в очереди
    def_channel, def_exe, def_profile = _default_browser()
    browser_name = def_channel or (Path(def_exe).stem if def_exe else "chromium")
    log.debug("Playwright: браузер по умолчанию — %s", browser_name)

    # Все браузеры для перебора: (channel, exe, profile)
    all_browsers: list[tuple[str | None, str | None, str | None]] = [
        (def_channel, def_exe, def_profile),
        ("msedge", None, str(Path.home() / "AppData/Local/Microsoft/Edge/User Data")),
        ("chrome", None, str(Path.home() / "AppData/Local/Google/Chrome/User Data")),
    ]
    # Убираем дубликаты (если дефолтный — msedge или chrome)
    seen: set[str] = set()
    unique_browsers = []
    for ch, exe, prof in all_browsers:
        key = ch or exe or "builtin"
        if key not in seen:
            seen.add(key)
            unique_browsers.append((ch, exe, prof))

    with sync_playwright() as pw:
        # ── Шаг 1: тихое извлечение из профиля (браузер должен быть закрыт) ──
        for channel, exe, profile_path in unique_browsers:
            if not profile_path or not Path(profile_path).exists():
                continue
            kwargs = _launch_kwargs(channel, exe)
            try:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    headless=True,
                    timeout=5_000,
                    **kwargs,
                )
                ctx.new_page().goto("https://steamcommunity.com", timeout=8_000)
                raw = ctx.cookies("https://steamcommunity.com")
                ctx.close()
                cookies = {c["name"]: c["value"] for c in raw}
                val = cookies.get("steamLoginSecure", "")
                if val and "||" in val and not _jwt_expired(val):
                    log.info("Playwright: JWT cookie из профиля %s", channel or exe)
                    return cookies
            except Exception as e:
                log.debug("Playwright profile %s: %s", channel or exe, e)

        # ── Шаг 2: окно браузера — пользователь логинится сам ──
        if not visible_fallback:
            return None
        log.info("Playwright: открываю %s для входа в Steam...", browser_name)
        print("\n[Steam] Войди в аккаунт в открывшемся браузере — окно закроется само\n")

        for channel, exe, _ in unique_browsers:
            kwargs = _launch_kwargs(channel, exe)
            try:
                browser = pw.chromium.launch(headless=False, **kwargs)
                ctx = browser.new_context()
                page = ctx.new_page()
                page.goto("https://steamcommunity.com/login/home/", timeout=15_000)

                # Ждём ухода со страницы логина — Steam редиректит после успешного входа
                try:
                    page.wait_for_url(lambda url: "/login" not in url, timeout=300_000)
                except Exception:
                    pass  # таймаут — попробуем взять cookie как есть

                raw = ctx.cookies("https://steamcommunity.com")
                cookies = {c["name"]: c["value"] for c in raw}
                val = cookies.get("steamLoginSecure", "")
                ctx.close()
                browser.close()
                if val and "||" in val:
                    _save_manual_cookie(val)
                    log.info("Playwright: JWT cookie получен (%s)", channel or exe or "chromium")
                    return cookies
                log.debug("Playwright: cookies после входа: %s", list(cookies.keys()))
            except Exception as e:
                log.debug("Playwright launch %s: %s", channel or exe, e)

    return None


def _cdp_steam_cookies() -> dict | None:
    """Подключается к запущенному браузеру через CDP (Chrome DevTools Protocol).

    Ищет --remote-debugging-port=XXXX в командной строке всех Chromium-процессов
    через psutil. Если находит — читает steamcommunity.com куки напрямую,
    минуя файловые блокировки и шифрование SQLite.

    Требует запуска браузера с флагом --remote-debugging-port=XXXX.
    """
    try:
        import psutil
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    # Сканируем командные строки всех процессов
    port: int | None = None
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []
            if not any(b in name for b in ("browser.exe", "chrome.exe", "msedge.exe")):
                continue
            for arg in cmdline:
                if isinstance(arg, str) and arg.startswith("--remote-debugging-port="):
                    p = arg.split("=", 1)[1]
                    if p.isdigit() and int(p) > 0:
                        port = int(p)
                        break
            if port:
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not port:
        return None

    log.debug("CDP: найден remote-debugging-port=%d", port)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(
                f"http://localhost:{port}", timeout=5_000
            )
            for ctx in browser.contexts:
                raw = ctx.cookies("https://steamcommunity.com")
                cookies = {c["name"]: c["value"] for c in raw}
                val = cookies.get("steamLoginSecure", "")
                if val and "||" in val and not _jwt_expired(val):
                    log.info("CDP: JWT cookie получен (порт %d)", port)
                    browser.close()
                    return cookies
            browser.close()
    except Exception as e:
        log.debug("CDP порт %d: %s", port, e)

    return None


def _browser_cookies_silent() -> dict | None:
    """Тихое извлечение куки: CDP → Firefox (SQLite) → Chrome/Edge (DPAPI) → Playwright headless.

    Не требует ввода данных. CDP работает даже когда браузер запущен.
    SQLite может не сработать если браузер держит файл заблокированным.
    """
    # CDP — лучший вариант: браузер запущен, порт открыт, читаем из памяти
    cookies = _cdp_steam_cookies()
    if cookies:
        return cookies

    cookies = _firefox_steam_cookies()
    if cookies:
        return cookies

    cookies = _chrome_steam_cookies()
    if cookies:
        return cookies

    return _playwright_steam_cookies(visible_fallback=False)


def _browser_cookies() -> dict | None:
    """Читает Steam Community куки из браузеров (включая открытие окна браузера)."""
    return _playwright_steam_cookies(visible_fallback=True)


def _jwt_expired(cookie_val: str) -> bool:
    """Проверяет срок действия JWT access token без обращения к серверу.

    steamLoginSecure = "{steamid64}||{jwt}". JWT payload содержит поле exp (unix ts).
    """
    try:
        token = cookie_val.split("||", 1)[1] if "||" in cookie_val else cookie_val
        # JWT = header.payload.signature — декодируем только payload
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)  # восстанавливаем padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp", 0)
        return time.time() > exp - 60  # считаем просроченным за 60с до истечения
    except Exception:
        return False  # не можем определить — считаем валидным


def _load_manual_cookie() -> dict | None:
    """Читает ручной steamLoginSecure cookie из файла."""
    if not _MANUAL_COOKIE_FILE.exists():
        return None
    try:
        val = _MANUAL_COOKIE_FILE.read_text(encoding="utf-8").strip()
        if "||" not in val or len(val.split("||", 1)[1]) < 100:
            return None  # не похоже на JWT формат
        if _jwt_expired(val):
            log.info("Сохранённый cookie истёк — нужен новый")
            return None
        log.info("Использую сохранённый steamLoginSecure cookie")
        return {"steamLoginSecure": val}
    except Exception:
        return None


def _save_manual_cookie(val: str) -> None:
    """Сохраняет steamLoginSecure cookie в файл для будущих запусков.

    Playwright возвращает значение в URL-encoded форме (%7C%7C вместо ||).
    Декодируем перед сохранением.
    """
    from urllib.parse import unquote
    val = unquote(val.strip())
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    _MANUAL_COOKIE_FILE.write_text(val.strip(), encoding="utf-8")
    log.info("Cookie сохранён в %s", _MANUAL_COOKIE_FILE)


def _save_remember_login(val: str) -> None:
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    _REMEMBER_LOGIN_FILE.write_text(val.strip(), encoding="utf-8")
    log.debug("steamRememberLogin сохранён")


def _web_refresh() -> dict | None:
    """Обновляет steamLoginSecure через steamRememberLogin без перелогина.

    steamRememberLogin — долгоживущий токен (месяцы), выданный Steam при входе.
    Steam обменивает его на новый steamLoginSecure при обращении к login/home.
    """
    if not _REMEMBER_LOGIN_FILE.exists():
        return None
    remember = _REMEMBER_LOGIN_FILE.read_text(encoding="utf-8").strip()
    if not remember:
        return None

    import urllib.request
    import http.cookiejar

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]

    # Добавляем steamRememberLogin вручную
    jar.set_cookie(_make_cookie("steamcommunity.com", "steamRememberLogin", remember))

    try:
        resp = opener.open("https://steamcommunity.com/login/home/?goto=", timeout=10)
        # Ищем новый steamLoginSecure в ответных cookies
        for c in jar:
            if c.name == "steamLoginSecure" and c.value and "||" in c.value:
                val = c.value
                _save_manual_cookie(val)
                log.info("Сессия обновлена через steamRememberLogin")
                return {"steamLoginSecure": val}
    except Exception as e:
        log.debug("web_refresh: %s", e)

    return None


def _make_cookie(domain: str, name: str, value: str):
    """Создаёт объект http.cookiejar.Cookie для ручной установки."""
    import http.cookiejar as cj
    return cj.Cookie(
        version=0, name=name, value=value, port=None, port_specified=False,
        domain=domain, domain_specified=True, domain_initial_dot=True,
        path="/", path_specified=True, secure=True, expires=None,
        discard=False, comment=None, comment_url=None, rest={},
    )


def _try_save_cm_refresh_token() -> None:
    """После браузерного входа сохраняет CM JWT refresh_token для автоматизации scan.py."""
    if _JWT_REFRESH_FILE.exists():
        return  # уже есть — ничего делать не нужно

    saved = _load_session()
    if not saved:
        return  # нет сохранённых credentials

    username, password = saved

    print("\n[Steam] scan.py тоже может работать без 2FA — нужно ввести код один раз.")
    answer = input("[Steam] Настроить автоматический вход для scan.py? [y/N]: ").strip().lower()
    if answer not in ("y", "yes", "д", "да"):
        return

    log.info("Получаю CM JWT refresh_token для автоматизации scan.py...")
    _jwt_web_cookies(username, password)


def _playwright_login() -> dict | None:
    """Открывает окно браузера для одноразового входа в Steam.

    Использует встроенный Playwright Chromium — никаких конфликтов с установленными
    браузерами. Ждёт появления steamLoginSecure JWT cookie (до 5 минут).
    Cookie сохраняется в manual_cookie.txt и живёт ~1 год.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.error("playwright не установлен: pip install playwright && python -m playwright install chromium")
        return None

    print("\n[Steam] Открываю браузер — войди в аккаунт, окно закроется само.")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            ctx = browser.new_context()
            page = ctx.new_page()
            page.goto("https://steamcommunity.com/login/home/", timeout=30_000, wait_until="domcontentloaded")

            # Ждём появления steamLoginSecure cookie — прямой признак успешного входа.
            # URL проверять ненадёжно: Steam может редиректить через /login/* страницы.
            deadline = time.time() + 300
            while time.time() < deadline:
                try:
                    raw = ctx.cookies("https://steamcommunity.com")
                except Exception:
                    break  # браузер закрыт пользователем
                val = next((c["value"] for c in raw if c["name"] == "steamLoginSecure"), "")
                if val:
                    ctx.close()
                    browser.close()
                    _save_manual_cookie(val)
                    # Сохраняем steamRememberLogin для обновления токена без перелогина
                    remember = next((c["value"] for c in raw if c["name"] == "steamRememberLogin"), "")
                    if remember:
                        _save_remember_login(remember)
                    log.info("Вход выполнен, cookie сохранён")
                    _try_save_cm_refresh_token()
                    return {c["name"]: c["value"] for c in raw}
                time.sleep(2)

            log.warning("Время ожидания входа истекло (5 мин)")
            ctx.close()
            browser.close()
    except Exception as e:
        log.error("Ошибка браузера: %s", e)

    return None


def get_web_cookies(username: str, *, interactive: bool = True) -> dict | None:
    """Возвращает JWT-куки веб-сессии Steam Community.

    Порядок попыток (все автоматические, без ввода данных):
      1. Сохранённый access token (~24ч)
      2. steamRememberLogin — web-обновление без перелогина (месяцы)
      3. JWT refresh token через CM — обновление без 2FA (месяцы)
      4. Браузер (один раз, потом пп. 1-3 работают автоматически)
    """
    # 1. Действующий сохранённый token
    cookies = _load_manual_cookie()
    if cookies:
        return cookies

    # 2. Обновление через steamRememberLogin (web, без CM)
    cookies = _web_refresh()
    if cookies:
        return cookies

    # 3. Обновление через JWT refresh token (CM протокол)
    cookies = _jwt_from_refresh_token()
    if cookies:
        _save_manual_cookie(cookies["steamLoginSecure"])
        return cookies

    if not interactive:
        log.info("Нет сохранённого cookie. Запусти скрипт интерактивно для входа.")
        return None

    # 4. Первичный вход через браузер (один раз)
    cookies = _playwright_login()
    if cookies:
        return cookies

    return None


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
    saved_username = saved[0] if saved else (
        _USERNAME_FILE.read_text(encoding="utf-8").strip() if _USERNAME_FILE.exists() else None
    )

    # Сначала JWT (без пароля и 2FA) — только CM-токен из refresh_token
    result = None
    if saved_username:
        jwt_cookies = _jwt_from_refresh_token()
        if jwt_cookies:
            access_token = jwt_cookies["steamLoginSecure"].split("||", 1)[1]
            result = _cm_login_with_jwt(client, saved_username, access_token, _CONNECT_TIMEOUT)
            if result == EResult.OK:
                log.info("Steam CM: вход через JWT (%s)", saved_username)
            else:
                log.debug("Steam CM: JWT не принят (%s), пробую пароль", result)

    if result != EResult.OK and saved:
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
            shared = _load_shared_secret(saved_username)
            two_factor_code = _compute_steam_totp(shared) if shared else None
            if two_factor_code:
                log.info("Steam CM: 2FA код сгенерирован автоматически")
            else:
                two_factor_code = input("[Steam CM] Введи 2FA код: ").strip()
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

    if not saved and result != EResult.OK:
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
        log.info("Steam CM: данные сохранены (%s)", _USERNAME_FILE)

    client.disconnect()

    if not owned_packages:
        log.warning("Steam CM: список лицензий пуст")
        return []

    return _expand_packages_to_apps(steam_path, owned_packages)
