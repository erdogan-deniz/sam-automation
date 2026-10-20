"""Пакет авто-добавления бесплатного контента Steam в библиотеку.

Субмодули:
  discovery    — кандидаты по полному каталогу (GetAppList + GetItems)
  state        — resume-состояние (candidates/added/refused/error)
  licenses     — батчевый request_free_license + cap-детект + backoff
  report       — честный итоговый отчёт (toast + Telegram)
  orchestrate  — склейка фаз discover/add, точка входа для CLI
"""

from .orchestrate import run

__all__ = ["run"]
