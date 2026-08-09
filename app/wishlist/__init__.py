"""Пакет авто-добавления каталога Steam в вишлист аккаунта.

Субмодули:
  discovery    — вселенная (GetAppList) минус owned/wishlisted (Web API дедуп)
  state        — resume-состояние (candidates/added/refused/error)
  wishlist_api — POST IWishlistService/AddToWishlist, x-eresult классификатор,
                 адаптивный backoff/wall
  report       — честный итоговый отчёт (toast + Telegram)
  orchestrate  — склейка фаз discover/add, точка входа для CLI
"""

from __future__ import annotations

from .orchestrate import run
from .wishlist_api import AddResult

__all__ = ["AddResult", "run"]
