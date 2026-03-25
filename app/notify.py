"""Windows toast-уведомления через PowerShell (без внешних зависимостей)."""

from __future__ import annotations

import logging
import subprocess

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
            ["powershell", "-WindowStyle", "Hidden", "-NonInteractive", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:
        log.debug("Toast уведомление не отправлено: %s", e)
