#!/usr/bin/env python
"""CI-гейт консистентности версии.

Проверяет инвариант: VERSION-файл == верхняя секция CHANGELOG (## [X.Y.Z]).
Ловит «забытый бамп» до релиза (прецедент v1.3.0: тег указал на VERSION=1.2.0).
Сверку с последним git-тегом делает release-ветка вручную — здесь только то,
что можно проверить на любом push/PR без сети.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_HEADING = re.compile(r"^##\s*\[(\d+\.\d+\.\d+)\]", re.MULTILINE)


def main() -> int:
    # CI-раннер Windows пишет stdout в cp1252 → кириллица в print() падает
    # UnicodeEncodeError. Тот же приём, что app.logging_setup.ensure_utf8_stdout.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    match = _HEADING.search(changelog)
    if match is None:
        print("CHANGELOG.md: не найдена верхняя секция '## [X.Y.Z]'.")
        return 1

    top = match.group(1)
    if version != top:
        print(
            f"Рассинхрон версии: VERSION={version} != верх CHANGELOG [{top}]. "
            "Синхронизируй VERSION и CHANGELOG перед релизом."
        )
        return 1

    print(f"Версия консистентна: VERSION == верх CHANGELOG == {version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
