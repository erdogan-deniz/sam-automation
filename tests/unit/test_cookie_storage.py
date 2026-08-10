"""Тесты app/cookies/storage.py — срок действия JWT и хранение кук.

Закрывают крупнейший пробел покрытия подпакета app/cookies: именно
_jwt_expired решает «кука ещё рабочая или нужен новый вход», а _load_manual_cookie
гейтит формат. Логика чистая — тестируется без сети и браузера.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import pytest

import app.cookies.storage as st

_STEAMID = "76561198000000000"


def _make_cookie(exp: float, *, steamid: str = _STEAMID) -> str:
    """Строит steamLoginSecure = '{steamid64}||{jwt}' с заданным exp."""
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": int(exp)}).encode())
        .decode()
        .rstrip("=")
    )
    token = f"hdr.{payload}.{'s' * 100}"  # подпись длинная → token >= 100 симв.
    return f"{steamid}||{token}"


def _patch_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    cookie = tmp_path / "manual_cookie.txt"
    monkeypatch.setattr(st, "_CRED_DIR", tmp_path)
    monkeypatch.setattr(st, "_MANUAL_COOKIE_FILE", cookie)
    monkeypatch.setattr(st, "_REMEMBER_LOGIN_FILE", tmp_path / "remember.txt")
    return cookie


# ── _jwt_expired ────────────────────────────────────────────────────────────


def test_jwt_expired_false_for_future_exp() -> None:
    assert st._jwt_expired(_make_cookie(time.time() + 3600)) is False


def test_jwt_expired_true_for_past_exp() -> None:
    assert st._jwt_expired(_make_cookie(time.time() - 3600)) is True


def test_jwt_expired_true_within_60s_grace() -> None:
    # Считаем просроченным за 60с до истечения — чтобы не начать прогон
    # с куки, которая умрёт в процессе.
    assert st._jwt_expired(_make_cookie(time.time() + 30)) is True


def test_jwt_expired_handles_token_without_steamid_prefix() -> None:
    # Без '||' весь val трактуется как сам JWT.
    full = _make_cookie(time.time() + 3600)
    bare_token = full.split("||", 1)[1]
    assert st._jwt_expired(bare_token) is False


def test_jwt_expired_false_when_payload_unparseable() -> None:
    # ОСОЗНАННЫЙ fallback «не можем определить — считаем валидным»: срок
    # неизвестен, но рвать сессию из-за неразобранного payload не хотим —
    # реальную негодность поймает Steam при запросе.
    # (Известная LOW-находка аудита: повреждённый manual_cookie так проходит
    # дальше как рабочий; файл пишет наш же код, поэтому риск низкий.)
    assert st._jwt_expired("76561198000000000||не-jwt-мусор") is False


# ── _load_manual_cookie ─────────────────────────────────────────────────────


def test_load_manual_cookie_none_when_file_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_files(monkeypatch, tmp_path)
    assert st._load_manual_cookie() is None


def test_load_manual_cookie_none_without_separator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cookie = _patch_files(monkeypatch, tmp_path)
    cookie.write_text("нет-разделителя" * 20, encoding="utf-8")
    assert st._load_manual_cookie() is None


def test_load_manual_cookie_none_when_token_too_short(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Токен короче 100 символов — не похоже на JWT.
    cookie = _patch_files(monkeypatch, tmp_path)
    cookie.write_text(f"{_STEAMID}||короткий", encoding="utf-8")
    assert st._load_manual_cookie() is None


def test_load_manual_cookie_none_when_expired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cookie = _patch_files(monkeypatch, tmp_path)
    cookie.write_text(_make_cookie(time.time() - 3600), encoding="utf-8")
    assert st._load_manual_cookie() is None


def test_load_manual_cookie_returns_valid_cookie(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cookie = _patch_files(monkeypatch, tmp_path)
    val = _make_cookie(time.time() + 3600)
    cookie.write_text(val, encoding="utf-8")
    assert st._load_manual_cookie() == {"steamLoginSecure": val}


# ── _save_manual_cookie / _save_remember_login ──────────────────────────────


def test_save_manual_cookie_url_decodes_separator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Playwright отдаёт значение URL-encoded (%7C%7C вместо ||) — декодируем,
    # иначе _load_manual_cookie не найдёт разделитель и отбросит валидную куку.
    cookie = _patch_files(monkeypatch, tmp_path)
    st._save_manual_cookie(f"{_STEAMID}%7C%7Cjwt-token")
    assert cookie.read_text(encoding="utf-8") == f"{_STEAMID}||jwt-token"


def test_save_manual_cookie_roundtrips_through_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_files(monkeypatch, tmp_path)
    val = _make_cookie(time.time() + 3600)
    st._save_manual_cookie(val)
    assert st._load_manual_cookie() == {"steamLoginSecure": val}


def test_save_manual_cookie_creates_missing_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    deep = tmp_path / "a" / "b"
    monkeypatch.setattr(st, "_CRED_DIR", deep)
    monkeypatch.setattr(st, "_MANUAL_COOKIE_FILE", deep / "manual_cookie.txt")
    st._save_manual_cookie(f"{_STEAMID}||tok")
    assert (deep / "manual_cookie.txt").exists()


def test_save_remember_login_strips_and_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(st, "_CRED_DIR", tmp_path)
    remember = tmp_path / "remember.txt"
    monkeypatch.setattr(st, "_REMEMBER_LOGIN_FILE", remember)
    st._save_remember_login("  token-value  \n")
    assert remember.read_text(encoding="utf-8") == "token-value"


def test_save_manual_cookie_uses_atomic_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Прямой Path.write_text открывает файл на запись (truncate) ДО записи —
    # краш/Ctrl+C между усечением и записью оставляет пустой/битый cookie-
    # файл (единственную сохранённую сессию). Должен идти через
    # _atomic_write_text (tmp-файл + os.replace), как id_file/cache.
    cookie = _patch_files(monkeypatch, tmp_path)
    calls = []
    monkeypatch.setattr(
        st, "_atomic_write_text", lambda p, t: calls.append((p, t))
    )
    st._save_manual_cookie(f"{_STEAMID}||tok")
    assert calls == [(cookie, f"{_STEAMID}||tok")]


def test_save_remember_login_uses_atomic_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(st, "_CRED_DIR", tmp_path)
    remember = tmp_path / "remember.txt"
    monkeypatch.setattr(st, "_REMEMBER_LOGIN_FILE", remember)
    calls = []
    monkeypatch.setattr(
        st, "_atomic_write_text", lambda p, t: calls.append((p, t))
    )
    st._save_remember_login("token-value")
    assert calls == [(remember, "token-value")]
