"""Уведомления: Windows toast (локально) + Telegram (удалённо).

Обе функции best-effort и без внешних зависимостей: ошибки только логируются,
вызывающий скрипт никогда не падает из-за уведомления.
"""

from __future__ import annotations

import logging
import subprocess
import urllib.parse
import urllib.request

from app.config import Config

log = logging.getLogger("sam_automation")

_APP_ID = "SAM Automation"

_PS_TEMPLATE = """\
[void][Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]
$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
    [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$nodes = $xml.GetElementsByTagName('text')
$nodes[0].InnerText = {title!r}
$nodes[1].InnerText = {message!r}
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier({app_id!r}).Show($toast)
"""


def toast(title: str, message: str) -> None:
    """Показывает Windows toast-уведомление. Молчаливо игнорирует ошибки."""
    script = _PS_TEMPLATE.format(title=title, message=message, app_id=_APP_ID)
    try:
        subprocess.Popen(
            [
                "powershell",
                "-WindowStyle",
                "Hidden",
                "-NonInteractive",
                "-Command",
                script,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:
        log.debug("Toast уведомление не отправлено: %s", e)


def send_telegram(text: str, cfg: Config) -> None:
    """Шлёт text в Telegram, если заданы telegram_bot_token и telegram_chat_id.

    Пусто → silent no-op (уведомления отключены). Сетевые/HTTP ошибки только
    логируются (WARNING), никогда не пробрасываются — вызывающий скрипт не падает.
    """
    # getattr, а не прямой доступ: цикловые тесты передают duck-typed cfg
    # (SimpleNamespace) без telegram-полей — для них это тихий no-op.
    token = getattr(cfg, "telegram_bot_token", "")
    chat_id = getattr(cfg, "telegram_chat_id", "")
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(url, data=data)
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        log.warning("Telegram уведомление не отправлено: %s", e)
