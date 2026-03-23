"""Скачивание SAM (SteamAchievementManager) с GitHub."""

from __future__ import annotations

import io
import json
import logging
import os
import urllib.request
import zipfile
from pathlib import Path

log = logging.getLogger("sam_automation")

SAM_REPO = "gibbed/SteamAchievementManager"
SAM_API_URL = f"https://api.github.com/repos/{SAM_REPO}/releases/latest"


def _fetch_latest_release() -> dict:
    """Запрашивает последний релиз SAM с GitHub API."""
    req = urllib.request.Request(SAM_API_URL)
    req.add_header("User-Agent", "SAM-Automation")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_for_update(sam_dir: Path) -> tuple[bool, str]:
    """Проверяет, доступна ли новая версия SAM.

    Returns:
        (needs_update, latest_tag)
    """
    release = _fetch_latest_release()
    latest_tag = release.get("tag_name", "")
    installed = _read_installed_version(sam_dir)
    return installed != latest_tag, latest_tag


def _save_version(sam_dir: Path, tag_name: str) -> None:
    """Сохраняет tag_name установленной версии SAM в <sam_dir>/.sam_version."""
    (sam_dir / ".sam_version").write_text(tag_name, encoding="utf-8")


def _read_installed_version(sam_dir: Path) -> str | None:
    """Возвращает tag_name из .sam_version, или None если файл отсутствует."""
    version_file = sam_dir / ".sam_version"
    try:
        return version_file.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def download_sam(target_dir: str, release: dict | None = None) -> str:
    """Скачивает SAM с GitHub и распаковывает.

    Args:
        target_dir: Директория для распаковки.
        release:    Уже полученный dict релиза (опционально).
                    Если None — запрашивается с GitHub.
    Returns:
        Путь к SAM.Game.exe
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)

    log.info("Скачиваю SAM с GitHub (%s) ...", SAM_REPO)
    if release is None:
        release = _fetch_latest_release()

    zip_url = None
    for asset in release.get("assets", []):
        if asset["name"].lower().endswith(".zip"):
            zip_url = asset["browser_download_url"]
            break

    if not zip_url:
        raise RuntimeError(
            f"Не найден ZIP в релизе {release.get('tag_name', '?')}. "
            f"Скачай SAM вручную: https://github.com/{SAM_REPO}/releases"
        )

    log.info("Скачиваю %s ...", zip_url)
    req = urllib.request.Request(zip_url)
    req.add_header("User-Agent", "SAM-Automation")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()

    log.info("Распаковываю в %s ...", target)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(target)

    for root, dirs, files in os.walk(target):
        for f in files:
            if f.lower() == "sam.game.exe":
                exe_path = os.path.join(root, f)
                log.info("SAM скачан: %s", exe_path)
                _save_version(target, release["tag_name"])
                return exe_path

    raise RuntimeError(
        f"SAM.Game.exe не найден после распаковки в {target}. "
        f"Скачай SAM вручную: https://github.com/{SAM_REPO}/releases"
    )


def ensure_sam(exe_path: str) -> str:
    """Проверяет наличие SAM.Game.exe. Если нет — скачивает.

    Returns:
        Актуальный путь к SAM.Game.exe
    """
    if Path(exe_path).exists():
        return exe_path

    log.warning("SAM.Game.exe не найден по пути: %s", exe_path)
    sam_dir = Path(exe_path).parent
    return download_sam(str(sam_dir))


def check_steam_running() -> bool:
    """Проверяет, запущен ли Steam."""
    try:
        import psutil

        for proc in psutil.process_iter(["name"]):
            if proc.info["name"] and proc.info["name"].lower() in (
                "steam.exe",
                "steam",
            ):
                return True
    except Exception:
        pass
    return False
