"""Steam Guard TOTP (Time-based One-Time Password)."""

from __future__ import annotations

import base64
import time


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
