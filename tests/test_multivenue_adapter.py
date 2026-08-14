from __future__ import annotations

import asyncio

from arbscanner.funding.multivenue import CcxtVenueAdapter


class FakeExchange:
    id = "fake"
    has = {"fetchPositions": True, "fetchOrder": True}
    markets = {"BTC/USDT:USDT": {"active": True, "swap": True}}

    async def load_markets(self, reload: bool = False): return self.markets
    async def fetch_funding_rate(self, symbol): return {"fundingRate": 0.0003, "nextFundingTimestamp": 1786675200000, "timestamp": 1786670000000}
    async def fetch_order_book(self, symbol, limit=None): return {"bids": [[100000, 1]], "asks": [[100010, 1]], "timestamp": 1786670000000}
    async def fetch_balance(self): return {"free": {"USDT": 1000}}
    async def fetch_positions(self, symbols=None): return []
    async def create_order(self, symbol, type, side, amount, price=None, params=None): return {"id": "o1", "status": "closed", "filled": amount}
    async def fetch_order(self, id, symbol=None, params=None): return {"id": id, "status": "closed", "filled": 0.01}
    async def close(self): return None


def test_quote_and_preflight() -> None:
    async def run():
        adapter = CcxtVenueAdapter("mexc", FakeExchange())
        q = await adapter.quote("BTC/USDT:USDT")
        pf = await adapter.private_preflight("BTC/USDT:USDT", 500)
        return q, pf
    quote, preflight = asyncio.run(run())
    assert quote.funding_rate == 0.0003
    assert quote.bid == 100000
    assert preflight["ready"] is True
