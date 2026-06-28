"""JWT refresh-токен и CM-логин через access_token."""

from __future__ import annotations

import json
import logging
from typing import Any

from ._constants import _CRED_DIR, _JWT_REFRESH_FILE

log = logging.getLogger("sam_automation")


def _save_jwt_refresh(steamid: str, refresh_token: str) -> None:
    """Сохраняет JWT refresh-токен на диск для повторного использования без 2FA."""
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


def _cm_login_with_jwt(
    client: Any, username: str, access_token: str, connect_timeout: int
) -> Any:
    """Логинится в Steam CM используя JWT access_token (без пароля и 2FA)."""
    import gevent
    from gevent.event import Event as GEvent
    from steam.core.msg import MsgProto
    from steam.enums import EResult
    from steam.enums.emsg import EMsg

    # После неудачного legacy-входа CM-канал мог остаться в нерабочем
    # состоянии — начинаем JWT-логон с чистого соединения.
    if client.connected:
        client.disconnect()
        client.sleep(1)

    connected = False
    with gevent.Timeout(connect_timeout, False):
        connected = client.connect()
    if not connected:
        log.warning(
            "Steam CM (JWT): не удалось подключиться к CM за %dс",
            connect_timeout,
        )
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

    if not auth_event.wait(timeout=30):
        # Ответа на ClientLogon нет: токен не принят CM либо канал не готов.
        log.warning(
            "Steam CM (JWT): нет ответа ClientLogOnResponse за 30с "
            "(токен не принят CM или соединение не готово)"
        )
        client.disconnect()
        return None

    result = result_holder[0]
    if result != EResult.OK:
        log.warning(
            "Steam CM (JWT): логон отклонён: %s",
            getattr(result, "name", result),
        )
        client.disconnect()

    return result
