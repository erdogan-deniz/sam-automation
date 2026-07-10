# Handoff-промпты

Заземлённые промпты для новых чатов, посвящённых отдельной фиче/задаче.
Каждый собран из реального кода (workflow: параллельные читатели → синтез →
адверсариальная сверка) и рассчитан на копипаст целиком в новую сессию.

| Файл | Назначение |
| --- | --- |
| [project-auditor.md](project-auditor.md) | Аудитор-чистильщик: мусор, dead-код, дрейф доков/версий, пробелы в тестах, нарушения архитектуры. Работает аудит-сначала (репорт → верификация → правки по согласию). |
| [scan.md](scan.md) | Фича `scripts/scan.py`: сбор App ID библиотеки из трёх источников (VDF + Steam API + CM) → `all.txt`. |
| [achievements-farm.md](achievements-farm.md) | Фича `scripts/achievements/farm.py`: разблокировка достижений через SAM (money-path; UIA-детект, run-lock, терминальный `without.txt`). |
| [cards-farm.md](cards-farm.md) | Фича `scripts/cards/farm.py`: фарм Steam trading cards (скрейп badges/gamecards, `_farm_loop`, run-lock). |
| [playtime-boost.md](playtime-boost.md) | Фича `scripts/playtime/boost.py`: набивка playtime батчами (источник правды — Steam API `playtime_forever`). |

Перед стартом заполни в промпте секцию задачи/симптома. Примеры-зацепки внутри
промптов датированы моментом сборки — проверяй актуальность на месте (код
меняется).
