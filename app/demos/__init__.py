"""Пакет авто-добавления demo-версий игр Steam в библиотеку.

Отделён от app/free_games (2026-09-12, B-11) — раньше демо были побочным
эффектом add_free.py (category1=10 внутри общей discovery). Собственный
resume-state, не пересекается с free_games.

Субмодули:
  discovery    — обнаружение кандидатов через store search (категория Demos)
  state        — resume-состояние (candidates/added/refused/error)
  report       — честный итоговый отчёт (toast + Telegram)
  orchestrate  — склейка фаз discover/add, точка входа для CLI

Выдача лицензий переиспользует app.free_games.licenses (add_licenses/
request_free_license) — тот же generic CM-механизм, не free_games-специфика.
"""

from .orchestrate import run

__all__ = ["run"]
