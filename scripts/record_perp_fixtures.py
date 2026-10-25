"""Record trimmed PUBLIC perp market-data fixtures from ccxt (no API keys, GET only).

Usage: ``uv run python scripts/record_perp_fixtures.py [venue ...]``. Writes
``tests/fixtures/perp/<venue>/*.json`` with the unified ccxt structures the adapters parse.
Unit tests never touch the network; they replay these files. The ccxt clients are created
without credentials and the read-only guard is installed, like the production adapters.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import ccxt.async_support as ccxt_async

from nexus.adapters.cex.ccxt_base import install_read_only_guard

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "perp"
VENUES = {
    "okx": ("okx", {"fetchMarkets": {"types": ["swap"]}, "defaultType": "swap"}),
    "kucoin": ("kucoinfutures", {}),
    "binance": ("binanceusdm", {}),
}
KEEP_BASES = ("BTC", "ETH", "DOGE")
BOOK_SYMBOL = "BTC/USDT:USDT"
BOOK_DEPTH = 20


def _dump(venue: str, name: str, payload: Any) -> None:
    path = OUT / venue / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str) + "\n")


def _keep(symbols: list[str], markets: dict[str, Any]) -> list[str]:
    """Majors plus the first odd-contract-size and the first inactive/non-linear samples."""
    wanted = [s for s in symbols if markets[s]["base"] in KEEP_BASES]
    odd = [s for s in sorted(symbols) if markets[s].get("contractSize") not in (1, 1.0, None)]
    return sorted({*wanted, *odd[:2]})


async def record(venue: str) -> None:
    ccxt_id, options = VENUES[venue]
    client = getattr(ccxt_async, ccxt_id)(
        {
            "enableRateLimit": True,
            "options": {"fetchCurrencies": False, **options},
        }
    )
    if client.apiKey:  # public data only
        msg = "fixture recording must run without credentials"
        raise SystemExit(msg)
    install_read_only_guard(client, f"{venue}:perp-fixtures")
    try:
        markets = await client.load_markets(True)
        swaps = {
            s: m
            for s, m in markets.items()
            if m.get("swap") and m.get("linear") and m["quote"] == "USDT"
        }
        keep = _keep(sorted(swaps), swaps)
        others = [s for s, m in markets.items() if s not in swaps and m.get("contract")][
            :2
        ]  # inverse / non-USDT samples exercise the filter
        spot = [s for s, m in markets.items() if m.get("spot")][:1]
        _dump(venue, "markets", {s: markets[s] for s in [*keep, *others, *spot]})
        tickers = await client.fetch_tickers()
        _dump(venue, "tickers", {s: tickers[s] for s in keep if s in tickers})
        if client.has.get("fetchBidsAsks"):
            bids_asks = await client.fetch_bids_asks()
            _dump(venue, "bids_asks", {s: bids_asks[s] for s in keep if s in bids_asks})
        marks = await client.fetch_mark_prices()
        _dump(venue, "mark_prices", {s: marks[s] for s in keep if s in marks})
        rates = (
            await client.fetch_funding_rates()
            if venue != "okx"
            else {s: await client.fetch_funding_rate(s) for s in keep}
        )
        _dump(venue, "funding", {s: rates[s] for s in keep if s in rates})
        if venue == "binance":
            intervals = await client.fetch_funding_intervals()
            odd = [s for s in sorted(intervals) if intervals[s].get("interval") != "8h"][:2]
            _dump(
                venue,
                "funding_intervals",
                {s: intervals[s] for s in [*keep, *odd] if s in intervals},
            )
        _dump(venue, "order_book", await client.fetch_order_book(BOOK_SYMBOL, BOOK_DEPTH))
        now = int(time.time() * 1000)
        klines = await client.fetch_mark_ohlcv(BOOK_SYMBOL, "1m", now - 3_600_000, 100)
        _dump(venue, "klines", klines)
        history = await client.fetch_funding_rate_history(BOOK_SYMBOL, None, 10)
        _dump(venue, "funding_history", history)
        if venue != "binance":  # Binance leverageBracket is signed: never called
            tiers = await client.fetch_market_leverage_tiers(BOOK_SYMBOL)
            _dump(venue, "tiers", tiers)
    finally:
        await client.close()


async def main(venues: list[str]) -> None:
    for venue in venues or list(VENUES):
        await record(venue)
        print("recorded", venue)  # noqa: T201


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
