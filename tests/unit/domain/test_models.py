from decimal import Decimal as D

import pytest

from nexus.domain.errors import InvalidOrderBookError
from nexus.domain.models import OrderBook, PriceLevel


def _book(bids: list[tuple[str, str]], asks: list[tuple[str, str]]) -> OrderBook:
    return OrderBook(
        exchange="x",
        symbol="BTC/USDT",
        bids=tuple(PriceLevel(D(p), D(a)) for p, a in bids),
        asks=tuple(PriceLevel(D(p), D(a)) for p, a in asks),
        timestamp_ms=1_000,
        received_at_ms=1_200,
    )


def test_best_prices() -> None:
    book = _book([("99", "1"), ("98", "2")], [("100", "1"), ("101", "3")])
    assert book.best_bid == D(99)
    assert book.best_ask == D(100)


def test_empty_book_has_no_best_prices() -> None:
    book = _book([], [])
    assert book.best_bid is None
    assert book.best_ask is None


def test_age_uses_older_timestamp() -> None:
    assert _book([], []).age_ms(now_ms=3_000) == 2_000


@pytest.mark.parametrize(
    ("bids", "asks"),
    [
        ([("99", "1"), ("100", "1")], [("101", "1")]),  # bids ascending
        ([("99", "1")], [("101", "1"), ("100", "1")]),  # asks descending
        ([("100", "1")], [("100", "1")]),  # crossed / locked
        ([("99", "0")], [("100", "1")]),  # zero amount
        ([("-1", "1")], [("100", "1")]),  # negative price
        ([("99", "1"), ("99", "1")], [("100", "1")]),  # duplicate price
    ],
)
def test_invalid_books_rejected(bids: list[tuple[str, str]], asks: list[tuple[str, str]]) -> None:
    with pytest.raises(InvalidOrderBookError):
        _book(bids, asks)
