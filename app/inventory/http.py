"""Транспорт Steam Community для распродажи инвентаря (B-16).

Что снято живьём 19.10.2026:
  * хватает куки steamLoginSecure; sessionid Steam выдаёт сам в Set-Cookie на
    любой GET (достаточно JSON инвентаря) и принимает его же в POST (cookie и
    поле формы);
  * маркет из Python отвечает 429 вразнобой (тот же запрос то 429, то 200) —
    чтение ретраится с растущей паузой; POST не ретраится здесь (429 значит
    «не принято»), им управляет внешний backoff (wishlist_api.add_pending);
  * тело ответа бывает gzip.
Секреты (куки, sessionid) в логи и сообщения исключений не попадают.
"""

from __future__ import annotations

import gzip
import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from email.message import Message
from typing import Any

from app.exceptions import SAMError
from app.inventory.market import AuthExpired, RateLimited

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
_COMMUNITY = "https://steamcommunity.com"

GET_ATTEMPTS = 5
_GET_BACKOFF: tuple[float, ...] = (5.0, 15.0, 30.0, 60.0)

Send = Callable[[urllib.request.Request], tuple[int, Message, bytes]]


class HttpError(SAMError):
    """Неожиданный ответ или сбой транспорта (без секретов в тексте)."""


def _urlopen_send(req: urllib.request.Request) -> tuple[int, Message, bytes]:
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _decode(body: bytes) -> bytes:
    if body[:2] == b"\x1f\x8b":
        try:
            return gzip.decompress(body)
        except OSError:
            return body
    return body


def _loads(body: bytes) -> dict[str, Any] | None:
    try:
        parsed = json.loads(_decode(body).decode("utf-8", "replace"))
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


class SteamHttp:
    def __init__(
        self,
        login_cookie: str,
        *,
        send: Send = _urlopen_send,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._login = login_cookie
        self._send = send
        self._sleep = sleep
        self._sessionid: str | None = None

    # --- служебное -------------------------------------------------------

    def _cookie(self) -> str:
        parts = [f"steamLoginSecure={self._login}"]
        if self._sessionid:
            parts.append(f"sessionid={self._sessionid}")
        return "; ".join(parts)

    def _request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        extra: dict[str, str] | None = None,
    ) -> urllib.request.Request:
        req = urllib.request.Request(url, data=data)
        req.add_header("User-Agent", _UA)
        req.add_header("Accept", "*/*")
        req.add_header("Accept-Language", "en-US,en;q=0.9")
        req.add_header("Cookie", self._cookie())
        for k, v in (extra or {}).items():
            req.add_header(k, v)
        return req

    def _take_sessionid(self, headers: Message) -> None:
        for value in headers.get_all("Set-Cookie") or []:
            m = re.match(r"\s*sessionid=([0-9A-Za-z]+)", value)
            if m:
                self._sessionid = m.group(1)

    # --- публичное -------------------------------------------------------

    def ensure_session(self, steamid64: str) -> None:
        """Получает sessionid обычным GET (JSON инвентаря, 1 предмет)."""
        self.get_json(
            f"{_COMMUNITY}/inventory/{steamid64}/753/6?l=english&count=1"
        )
        if not self._sessionid:
            raise HttpError("Steam не выдал sessionid")

    def get_json(self, url: str) -> dict[str, Any]:
        last = "нет ответа"
        for attempt in range(GET_ATTEMPTS):
            try:
                status, headers, body = self._send(self._request(url))
            except (
                urllib.error.URLError,
                OSError,
                http.client.HTTPException,
            ) as e:
                status, headers, body = 0, Message(), b""
                last = f"сетевой сбой: {type(e).__name__}"
            if status in (401, 403):
                raise AuthExpired(f"HTTP {status}: сессия истекла")
            if status == 200:
                self._take_sessionid(headers)
                parsed = _loads(body)
                if parsed is None:
                    raise HttpError("ответ не JSON-объект")
                return parsed
            if status not in (0, 429) and status < 500:
                raise HttpError(
                    f"HTTP {status} на {urllib.parse.urlsplit(url).path}"
                )
            if status == 429:
                last = "429"
            elif status >= 500:
                last = f"HTTP {status} на {urllib.parse.urlsplit(url).path}"
            if attempt < GET_ATTEMPTS - 1:
                self._sleep(_GET_BACKOFF[min(attempt, len(_GET_BACKOFF) - 1)])
        if last == "429":
            raise RateLimited("429 на запросе после всех повторов")
        raise HttpError(last)

    def post_form(
        self, url: str, form: dict[str, str], referer: str
    ) -> tuple[int, dict[str, Any] | None]:
        if not self._sessionid:
            raise HttpError("нет sessionid: сначала ensure_session()")
        payload = urllib.parse.urlencode(
            {"sessionid": self._sessionid, **form}
        ).encode()
        req = self._request(
            url,
            data=payload,
            extra={
                "Referer": referer,
                "Origin": _COMMUNITY,
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            status, _headers, body = self._send(req)
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            return 0, None
        return status, _loads(body)
