"""Тесты app/inventory/fees.py: комиссия маркета в целых копейках (B-16)."""

from __future__ import annotations

import pytest

from app.inventory import fees


@pytest.mark.parametrize(
    ("received", "expected"),
    [
        (6958, 8000),  # живой лот владельца: 80 руб покупателю, 69,58 на руки
        (84, 252),  # минимум на обе части: 84 + 84 + 84
        (216, 384),
        (50000, 57500),  # пробный лот 19.10.2026: 500 руб -> 575 руб
        (1216, 1421),  # 5% ниже минимума, 10% выше него
    ],
)
def test_buyer_pays_matches_live_listings(received, expected) -> None:
    assert fees.buyer_pays(received, fees.min_fee(5)) == expected


@pytest.mark.parametrize(
    ("price", "expected"),
    [(8000, 6958), (252, 84), (384, 216), (5671, 4932), (57500, 50000)],
)
def test_received_from_buyer_is_inverse(price, expected) -> None:
    assert fees.received_from_buyer(price, fees.min_fee(5)) == expected


def test_roundtrip_every_amount() -> None:
    m = fees.min_fee(5)
    for received in range(0, 3000):
        price = fees.buyer_pays(received, m)
        assert fees.received_from_buyer(price, m) == received


def test_received_from_buyer_never_exceeds_price() -> None:
    m = fees.min_fee(5)
    for price in range(fees.buyer_pays(0, m), 3000):
        received = fees.received_from_buyer(price, m)
        assert fees.buyer_pays(received, m) <= price
        assert fees.buyer_pays(received + 1, m) > price


def test_price_below_minimum_fees_yields_zero() -> None:
    assert fees.received_from_buyer(100, fees.min_fee(5)) == 0


def test_min_fee_known_currency() -> None:
    assert fees.min_fee(5) == 84


def test_min_fee_unknown_currency_refuses() -> None:
    with pytest.raises(fees.UnknownCurrencyError):
        fees.min_fee(999)
