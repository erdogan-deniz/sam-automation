"""Скачивание SAM (SteamAchievementManager) с GitHub."""

from __future__ import annotations

import http.client
import io
import json
import logging
import shutil
import tempfile
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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (OSError, http.client.HTTPException) as e:
        raise RuntimeError(
            f"Не удалось получить релиз SAM с GitHub: {e}. Проверь сеть "
            f"или скачай вручную: https://github.com/{SAM_REPO}/releases"
        ) from e


def check_for_update(exe_path: str) -> str | None:
    """Проверяет наличие обновления SAM на GitHub и предлагает обновить.

    Returns:
        Новый путь к SAM.Game.exe если обновление установлено, иначе None.
    """
    exe_dir = Path(exe_path).parent
    release = _fetch_latest_release()
    latest = release["tag_name"]

    # Сравнение — тег-с-тегом: latest это GitHub tag ('rNN'), поэтому и
    # установленную версию берём как сохранённый тег (.sam_version). PE-метаданные
    # бинарника имеют формат 'x.y.z' и с тегом никогда не совпадут — сравнение с
    # ними давало «обновление доступно» КАЖДЫЙ запуск (вечный промпт 'Обновить?').
    installed_tag = _read_installed_tag(exe_dir)
    if installed_tag == latest:
        log.debug("SAM %s — последняя версия", latest)
        return None

    # PE-версия — только для человекочитаемого лога (не для сравнения).
    installed_display = _read_installed_version(exe_dir)
    if installed_display is None:
        log.info("Версия SAM неизвестна. Последняя: %s", latest)
    else:
        log.info("Текущая версия приложения SAM: %s", installed_display)
        log.info("Доступна новая версия приложения SAM: %s", latest)

    try:
        print()

        answer = (
            input("Обновить приложение SAM до последней версии? [YES/NO]: ")
            .strip()
            .lower()
        )
    except EOFError:
        log.info("Не интерактивный режим — пропускаю обновление SAM")
        return None

    if answer != "yes":
        return None

    return download_sam(str(exe_dir), release=release)


def _save_version(sam_dir: Path, tag_name: str) -> None:
    """Сохраняет tag_name установленной версии SAM в <sam_dir>/.sam_version."""
    (sam_dir / ".sam_version").write_text(tag_name, encoding="utf-8")


def _read_installed_tag(sam_dir: Path) -> str | None:
    """Возвращает сохранённый тег установленного SAM (<sam_dir>/.sam_version).

    Это ЕДИНСТВЕННЫЙ источник, сопоставимый с GitHub tag_name ('rNN') для
    определения «нужно ли обновление». PE-метаданные бинарника ('x.y.z') с
    тегом несравнимы — их формат другой. None, если тег не сохранён (SAM
    поставлен вручную или до появления .sam_version).
    """
    try:
        return (sam_dir / ".sam_version").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _read_installed_version(sam_dir: Path) -> str | None:
    """Возвращает версию установленного SAM.Game.exe.

    Сначала читает PE-метаданные бинарника (всегда точно),
    затем падает на .sam_version, затем возвращает None.
    """
    exe = sam_dir / "SAM.Game.exe"
    if exe.exists():
        try:
            import win32api

            info = win32api.GetFileVersionInfo(str(exe), "\\")
            ms, ls = info["FileVersionMS"], info["FileVersionLS"]
            major, minor, patch = ms >> 16, ms & 0xFFFF, ls >> 16
            return f"{major}.{minor}.{patch}"
        except Exception:
            pass

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
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except (OSError, http.client.HTTPException) as e:
        raise RuntimeError(
            f"Не удалось скачать SAM zip: {e}. "
            f"Скачай вручную: https://github.com/{SAM_REPO}/releases"
        ) from e

    log.info("Распаковываю в %s ...", target)
    exe_path: str | None = None

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            zf.extractall(tmp)

        locked: list[str] = []
        for src in tmp.rglob("*"):
            if not src.is_file():
                continue
            rel = src.relative_to(tmp)
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src), str(dst))
            except PermissionError:
                locked.append(str(rel))
                log.warning("Файл залочен, пропускаю: %s", rel)
            if dst.name.lower() == "sam.game.exe":
                exe_path = str(dst)

        if locked:
            log.warning(
                "Обновление частичное — %d файл(ов) не заменено (залочены):\n  %s",
                len(locked),
                "\n  ".join(locked),
            )

    if exe_path:
        log.info("SAM скачан: %s", exe_path)
        _save_version(target, release["tag_name"])
        return exe_path

    raise RuntimeError(
        f"SAM.Game.exe не найден после распаковки в {target}. "
        f"Скачай SAM вручную: https://github.com/{SAM_REPO}/releases"
    )


def ensure_sam(exe_path: str) -> str:
    """Проверяет наличие SAM.Game.exe. Если нет — скачивает.
    Если есть — проверяет наличие обновлений на GitHub.

    Returns:
        Актуальный путь к SAM.Game.exe
    """
    if not Path(exe_path).exists():
        log.warning("SAM.Game.exe не найден по пути: %s", exe_path)
        sam_dir = Path(exe_path).parent
        return download_sam(str(sam_dir))

    try:
        updated_path = check_for_update(exe_path)
        if updated_path:
            return updated_path
    except Exception as e:  # broad catch: network, API, or unexpected errors are all non-fatal here
        # Trade-off: a programming error in check_for_update (e.g. KeyError on API response)
        # is also caught and logged as a warning instead of crashing. This is acceptable
        # because the update check is a best-effort operation — the script must continue.
        log.warning("Не удалось проверить обновления SAM: %s", e)

    return exe_path


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
