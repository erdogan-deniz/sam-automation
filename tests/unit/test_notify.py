"""Тесты для app/notify.py (toast + Telegram уведомления)."""

from __future__ import annotations

from unittest.mock import patch

from app.config import Config
from app.notify import _ps_single_quote, send_telegram, toast


def test_ps_single_quote_wraps_literal() -> None:
    assert _ps_single_quote("abc") == "'abc'"


def test_ps_single_quote_doubles_apostrophe() -> None:
    # PS-литерал: единственная спецформа в одинарных кавычках — сам апостроф ('')
    assert _ps_single_quote("Baldur's Gate") == "'Baldur''s Gate'"


def test_toast_escapes_apostrophe_as_ps_literal() -> None:
    # Имя игры с апострофом (Steam-имя, неконтролируемо) не должно ломать PS:
    # Python repr на апострофе даёт ДВОЙНЫЕ кавычки → в PS интерполяция.
    with patch("app.notify.subprocess.Popen") as mock_popen:
        toast("Baldur's Gate", "готово")
        script = " ".join(mock_popen.call_args[0][0])
        assert "'Baldur''s Gate'" in script


def test_toast_does_not_interpolate_dollar() -> None:
    # '$'/backtick внутри одинарных кавычек PS — литералы, не исполнение.
    with patch("app.notify.subprocess.Popen") as mock_popen:
        toast("$(danger)", "M")
        script = " ".join(mock_popen.call_args[0][0])
        assert "'$(danger)'" in script


def test_toast_calls_popen() -> None:
    """toast() запускает subprocess.Popen."""
    with patch("app.notify.subprocess.Popen") as mock_popen:
        toast("Title", "Message")
        assert mock_popen.called


def test_toast_uses_powershell() -> None:
    """Первый аргумент команды — powershell."""
    with patch("app.notify.subprocess.Popen") as mock_popen:
        toast("T", "M")
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "powershell"


def test_toast_includes_title_and_message() -> None:
    """PowerShell-скрипт содержит переданные title и message."""
    with patch("app.notify.subprocess.Popen") as mock_popen:
        toast("My Title", "My Message")
        cmd = mock_popen.call_args[0][0]
        script = " ".join(cmd)
        assert "My Title" in script
        assert "My Message" in script


def test_toast_silent_on_error() -> None:
    """toast() не бросает исключение если Popen недоступен."""
    with patch("app.notify.subprocess.Popen", side_effect=FileNotFoundError):
        toast("T", "M")  # должно молча проглотить ошибку


def test_toast_silent_on_os_error() -> None:
    """toast() не бросает исключение при любой ошибке запуска."""
    with patch(
        "app.notify.subprocess.Popen", side_effect=OSError("access denied")
    ):
        toast("T", "M")


# ── send_telegram ─────────────────────────────────────────────────────────


def test_send_telegram_noop_when_no_token() -> None:
    """Пустой telegram_bot_token → нет сетевого вызова (silent no-op)."""
    cfg = Config(telegram_bot_token="", telegram_chat_id="123")
    with patch("app.notify.urllib.request.urlopen") as mock_urlopen:
        send_telegram("привет", cfg)
        assert not mock_urlopen.called


def test_send_telegram_noop_when_no_chat_id() -> None:
    """Пустой telegram_chat_id → нет сетевого вызова."""
    cfg = Config(telegram_bot_token="tok", telegram_chat_id="")
    with patch("app.notify.urllib.request.urlopen") as mock_urlopen:
        send_telegram("привет", cfg)
        assert not mock_urlopen.called


def test_send_telegram_posts_when_configured() -> None:
    """При заданных токене и chat_id шлёт POST на Bot API sendMessage."""
    cfg = Config(telegram_bot_token="BOT", telegram_chat_id="CHAT")
    with patch("app.notify.urllib.request.urlopen") as mock_urlopen:
        send_telegram("hello", cfg)
        assert mock_urlopen.called
        req = mock_urlopen.call_args[0][0]
        assert "botBOT/sendMessage" in req.full_url
        body = req.data.decode() if isinstance(req.data, bytes) else req.data
        assert "CHAT" in body
        assert "hello" in body


def test_send_telegram_silent_on_error() -> None:
    """Сетевая ошибка не пробрасывается — вызывающий скрипт не падает."""
    cfg = Config(telegram_bot_token="BOT", telegram_chat_id="CHAT")
    with patch(
        "app.notify.urllib.request.urlopen", side_effect=OSError("network")
    ):
        send_telegram("hi", cfg)  # должно молча проглотить
