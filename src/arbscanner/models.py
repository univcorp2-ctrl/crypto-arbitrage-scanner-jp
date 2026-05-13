from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PriceLevel:
    price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class OrderBook:
    exchange: str
    market: str
    bids: tuple[PriceLevel, ...]
    asks: tuple[PriceLevel, ...]
    raw_symbol: str
    timestamp: str | None = None

    @property
    def best_bid(self) -> PriceLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> PriceLevel | None:
        return self.asks[0] if self.asks else None


@dataclass(frozen=True)
class ExchangeConfig:
    name: str
    enabled: bool
    pair: str
    taker_fee_bps: Decimal

    @property
    def taker_fee_rate(self) -> Decimal:
        return self.taker_fee_bps / Decimal("10000")


@dataclass(frozen=True)
class Opportunity:
    market: str
    buy_exchange: str
    sell_exchange: str
    buy_ask: Decimal
    sell_bid: Decimal
    top_size: Decimal
    gross_spread_bps: Decimal
    net_spread_bps: Decimal
    net_profit_quote: Decimal
