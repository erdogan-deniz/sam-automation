"""Комиссия маркета Steam в целых минимальных единицах валюты (B-16).

Формула снята на 101 активном лоте владельца 19.10.2026 (100 % совпадений):
    покупатель = на_руки + max(m, ⌊5 % × на_руки⌋) + max(m, ⌊10 % × на_руки⌋)
m — минимальная комиссия валюты: для рублей 84 коп. (1 цент в рублях), а не
1 коп. На странице маркета `wallet_fee_minimum` больше нет, поэтому m лежит в
таблице; валюта вне таблицы — отказ, а не догадка. Float не используется.
"""

from __future__ import annotations

from app.exceptions import SAMError

# eCurrency Steam -> минимальная комиссия в минимальных единицах валюты.
_MIN_FEE: dict[int, int] = {
    5: 84,  # RUB, снято живьём 19.10.2026
}


class UnknownCurrencyError(SAMError):
    """Минимум комиссии для валюты кошелька неизвестен — продавать нельзя."""


def min_fee(currency: int) -> int:
    try:
        return _MIN_FEE[currency]
    except KeyError:
        raise UnknownCurrencyError(
            f"нет минимальной комиссии для валюты {currency}"
        ) from None


def buyer_pays(received: int, m: int) -> int:
    """Сколько заплатит покупатель, если продавцу должно остаться received."""
    return received + max(m, received * 5 // 100) + max(m, received * 10 // 100)


def received_from_buyer(price: int, m: int) -> int:
    """Наибольшая сумма на руки продавцу, при которой покупатель платит ≤ price.

    buyer_pays строго возрастает, поэтому подходит бинарный поиск.
    """
    if price < buyer_pays(0, m):
        return 0
    lo, hi = 0, price
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if buyer_pays(mid, m) <= price:
            lo = mid
        else:
            hi = mid - 1
    return lo
