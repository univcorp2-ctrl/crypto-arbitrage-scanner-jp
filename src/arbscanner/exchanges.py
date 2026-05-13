from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from .models import OrderBook, PriceLevel


class ExchangeError(RuntimeError):
    """Raised when an exchange response cannot be fetched or parsed."""


class ExchangeAdapter(Protocol):
    name: str

    async def fetch_orderbook(
        self,
        client: httpx.AsyncClient,
        *,
        market: str,
        pair: str,
    ) -> OrderBook:
        """Fetch a public order book snapshot."""


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ExchangeError(f"invalid decimal value: {value!r}") from exc


def _levels_from_pairs(rows: list[Any]) -> tuple[PriceLevel, ...]:
    levels: list[PriceLevel] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            raise ExchangeError(f"invalid price level: {row!r}")
        levels.append(PriceLevel(price=_decimal(row[0]), amount=_decimal(row[1])))
    return tuple(levels)


def _levels_from_objects(rows: list[Any]) -> tuple[PriceLevel, ...]:
    levels: list[PriceLevel] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ExchangeError(f"invalid price level: {row!r}")
        size_value = row.get("size", row.get("amount"))
        levels.append(PriceLevel(price=_decimal(row.get("price")), amount=_decimal(size_value)))
    return tuple(levels)


class BitbankAdapter:
    name = "bitbank"
    base_url = "https://public.bitbank.cc"

    async def fetch_orderbook(
        self,
        client: httpx.AsyncClient,
        *,
        market: str,
        pair: str,
    ) -> OrderBook:
        response = await client.get(f"{self.base_url}/{pair}/depth")
        response.raise_for_status()
        payload = response.json()
        if payload.get("success") != 1:
            raise ExchangeError(f"bitbank returned error payload: {payload!r}")
        data = payload.get("data") or {}
        return OrderBook(
            exchange=self.name,
            market=market,
            raw_symbol=pair,
            bids=_levels_from_pairs(data.get("bids") or []),
            asks=_levels_from_pairs(data.get("asks") or []),
            timestamp=str(data.get("timestamp")) if data.get("timestamp") is not None else None,
        )


class GmoCoinAdapter:
    name = "gmocoin"
    base_url = "https://api.coin.z.com/public/v1"

    async def fetch_orderbook(
        self,
        client: httpx.AsyncClient,
        *,
        market: str,
        pair: str,
    ) -> OrderBook:
        response = await client.get(f"{self.base_url}/orderbooks", params={"symbol": pair})
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") not in {0, "0"}:
            raise ExchangeError(f"GMO Coin returned error payload: {payload!r}")
        data = payload.get("data") or {}
        return OrderBook(
            exchange=self.name,
            market=market,
            raw_symbol=pair,
            bids=_levels_from_objects(data.get("bids") or []),
            asks=_levels_from_objects(data.get("asks") or []),
            timestamp=data.get("timestamp"),
        )


class BitflyerAdapter:
    name = "bitflyer"
    base_url = "https://api.bitflyer.com/v1"

    async def fetch_orderbook(
        self,
        client: httpx.AsyncClient,
        *,
        market: str,
        pair: str,
    ) -> OrderBook:
        response = await client.get(f"{self.base_url}/board", params={"product_code": pair})
        response.raise_for_status()
        data = response.json()
        return OrderBook(
            exchange=self.name,
            market=market,
            raw_symbol=pair,
            bids=_levels_from_objects(data.get("bids") or []),
            asks=_levels_from_objects(data.get("asks") or []),
            timestamp=None,
        )


class CoincheckAdapter:
    name = "coincheck"
    base_url = "https://coincheck.com"

    async def fetch_orderbook(
        self,
        client: httpx.AsyncClient,
        *,
        market: str,
        pair: str,
    ) -> OrderBook:
        response = await client.get(f"{self.base_url}/api/order_books", params={"pair": pair})
        response.raise_for_status()
        data = response.json()
        return OrderBook(
            exchange=self.name,
            market=market,
            raw_symbol=pair,
            bids=_levels_from_pairs(data.get("bids") or []),
            asks=_levels_from_pairs(data.get("asks") or []),
            timestamp=None,
        )


ADAPTERS: dict[str, ExchangeAdapter] = {
    "bitbank": BitbankAdapter(),
    "gmocoin": GmoCoinAdapter(),
    "bitflyer": BitflyerAdapter(),
    "coincheck": CoincheckAdapter(),
}
