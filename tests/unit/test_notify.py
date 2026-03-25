"""Тесты для app/notify.py (toast уведомления через PowerShell)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.notify import toast


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
    with patch("app.notify.subprocess.Popen", side_effect=OSError("access denied")):
        toast("T", "M")
