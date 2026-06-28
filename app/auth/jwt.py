"""JWT refresh-токен и CM-логин через access_token."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ._constants import _CRED_DIR, _JWT_REFRESH_FILE

log = logging.getLogger("sam_automation")


def _save_jwt_refresh(
    steamid: str, refresh_token: str, path: Path = _JWT_REFRESH_FILE
) -> None:
    """Сохраняет JWT refresh-токен на диск для повторного использования без 2FA.

    path различает scope токена (WebBrowser-куки vs SteamClient-логон в CM).
    """
    _CRED_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"steamid": steamid, "refresh_token": refresh_token}),
        encoding="utf-8",
    )
    log.debug("IAuthService: refresh_token сохранён (%s)", path.name)


def _jwt_from_refresh_token(path: Path = _JWT_REFRESH_FILE) -> dict | None:
    """Пробует получить новый access_token из кэшированного refresh_token.

    Не требует 2FA. Возвращает None если кэш пуст или токен истёк. path
    различает scope токена (WebBrowser-куки vs SteamClient-логон в CM).
    """
    if not path.exists():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        steamid = data.get("steamid", "")
        refresh_token = data.get("refresh_token", "")
        if not steamid or not refresh_token:
            return None
    except Exception:
        return None

    try:
        import gevent
        from steam.client import SteamClient
        from steam.enums import EResult

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
                log.debug(
                    "IAuthService: refresh_token истёк или недействителен"
                )
                path.unlink(missing_ok=True)
                return None

            access_token = resp.body.access_token
            if not access_token:
                path.unlink(missing_ok=True)
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


def _cm_login_with_jwt(
    client: Any, username: str, access_token: str, connect_timeout: int
) -> Any:
    """Логинится в Steam CM используя JWT access_token (без пароля и 2FA).

    Повторяет последовательность рабочего client.login(), но с access_token
    вместо пароля. Критично: _pre_login() не только подключается, но и ДОЖИДАЕТСЯ
    EVENT_CHANNEL_SECURED (шифрование канала) — без этого CM молча игнорирует
    ClientLogon (нет ответа). Заголовок ClientLogon обязан нести steamid для
    маршрутизации; ручная сборка без него и без channel_secured и давала таймаут.
    """
    import gevent
    from steam.core.msg import MsgProto
    from steam.enums import EOSType, EResult
    from steam.enums.emsg import EMsg
    from steam.steamid import SteamID

    # После неудачного legacy-входа канал мог зависнуть — чистое соединение.
    if client.connected:
        client.disconnect()
        client.sleep(1)

    # _pre_login: подключение + ожидание шифрования канала (channel_secured).
    eresult = None
    with gevent.Timeout(connect_timeout, False):
        eresult = client._pre_login()
    if eresult != EResult.OK:
        log.warning(
            "Steam CM (JWT): подготовка соединения не удалась: %s",
            getattr(eresult, "name", eresult),
        )
        return None

    client.username = username

    # ClientLogon как в client.login(), но с access_token вместо пароля.
    msg = MsgProto(EMsg.ClientLogon)
    msg.header.steamid = SteamID(type="Individual", universe="Public")
    msg.body.protocol_version = 65580
    msg.body.client_package_version = 1561159470
    msg.body.client_os_type = EOSType.Windows10
    msg.body.client_language = "english"
    msg.body.should_remember_password = True
    msg.body.supports_rate_limit_response = True
    msg.body.account_name = username
    msg.body.access_token = access_token
    client.send(msg)

    resp = client.wait_msg(EMsg.ClientLogOnResponse, timeout=30)
    if resp is None:
        log.warning(
            "Steam CM (JWT): нет ответа ClientLogOnResponse за 30с "
            "(токен не принят CM или соединение не готово)"
        )
        client.disconnect()
        return None

    result = EResult(resp.body.eresult)
    if result != EResult.OK:
        log.warning("Steam CM (JWT): логон отклонён: %s", result.name)
        client.disconnect()

    return result
