"""Разворачивание Steam пакетов → App ID через локальный packageinfo.vdf."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("sam_automation")


def expand_packages_to_apps(
    steam_path: str, owned_packages: set[int]
) -> list[int]:
    """Читает appcache/packageinfo.vdf и возвращает App ID для указанных пакетов."""
    pkginfo_path = Path(steam_path) / "appcache" / "packageinfo.vdf"
    if not pkginfo_path.exists():
        log.warning("packageinfo.vdf не найден: %s", pkginfo_path)
        return []

    from steam.utils.appcache import parse_packageinfo

    app_ids: list[int] = []
    seen: set[int] = set()
    found_pkgs = 0

    with open(pkginfo_path, "rb") as f:
        _header, pkgs_iter = parse_packageinfo(f)
        for pkg in pkgs_iter:
            # Один структурно битый пакет не должен ронять ВЕСЬ разбор
            # (иначе 0 CM-игр) — пропускаем только его.
            try:
                pkg_id = pkg.get("packageid")
                if pkg_id not in owned_packages:
                    continue
                found_pkgs += 1
                inner = pkg.get("data", {}).get(str(pkg_id), {})
                for app_id in inner.get("appids", {}).values():
                    if not isinstance(app_id, int):
                        log.debug(
                            "packageinfo: не-int appid %r в пакете %s — пропуск",
                            app_id,
                            pkg_id,
                        )
                        continue
                    if app_id not in seen:
                        seen.add(app_id)
                        app_ids.append(app_id)
            except Exception as e:
                pkg_id = pkg.get("packageid") if isinstance(pkg, dict) else "?"
                log.warning(
                    "packageinfo: пропущен битый пакет %s: %s", pkg_id, e
                )
                continue

    missing = len(owned_packages) - found_pkgs
    log.info(
        "Найдено %d ID приложений библиотеки Steam через Steam Client Master%s",
        len(app_ids),
        f" (пропущено пакетов: {missing})" if missing else "",
    )
    return app_ids
