from __future__ import annotations

import asyncio
from decimal import Decimal

import httpx

from .config import ScannerConfig
from .exchanges import ADAPTERS, ExchangeError
from .models import ExchangeConfig, Opportunity, OrderBook


async def fetch_orderbooks(config: ScannerConfig) -> tuple[list[OrderBook], dict[str, str]]:
    """Fetch enabled exchange order books concurrently.

    Returns a tuple of successful order books and per-exchange error messages.
    """

    timeout = httpx.Timeout(config.request_timeout_seconds)
    async with httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": "arbscanner/0.1"}
    ) as client:
        tasks = [
            _fetch_one(client, config.market, exchange_config)
            for exchange_config in config.exchanges
            if exchange_config.enabled
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    books: list[OrderBook] = []
    errors: dict[str, str] = {}
    for exchange_config, result in zip(
        [item for item in config.exchanges if item.enabled], results, strict=True
    ):
        if isinstance(result, Exception):
            errors[exchange_config.name] = str(result)
        else:
            books.append(result)
    return books, errors


async def _fetch_one(
    client: httpx.AsyncClient,
    market: str,
    exchange_config: ExchangeConfig,
) -> OrderBook:
    adapter = ADAPTERS.get(exchange_config.name)
    if adapter is None:
        raise ExchangeError(f"unsupported exchange: {exchange_config.name}")
    if not exchange_config.pair:
        raise ExchangeError(f"missing pair for exchange: {exchange_config.name}")
    book = await adapter.fetch_orderbook(client, market=market, pair=exchange_config.pair)
    if book.best_bid is None or book.best_ask is None:
        raise ExchangeError(f"empty order book for exchange: {exchange_config.name}")
    return book


def calculate_opportunities(
    books: list[OrderBook],
    exchange_configs: tuple[ExchangeConfig, ...],
    *,
    min_net_bps: Decimal = Decimal("0"),
) -> list[Opportunity]:
    fee_by_exchange = {config.name: config.taker_fee_rate for config in exchange_configs}
    opportunities: list[Opportunity] = []

    for buy_book in books:
        buy_ask = buy_book.best_ask
        if buy_ask is None:
            continue
        for sell_book in books:
            if sell_book.exchange == buy_book.exchange:
                continue
            sell_bid = sell_book.best_bid
            if sell_bid is None:
                continue

            buy_fee = fee_by_exchange.get(buy_book.exchange, Decimal("0"))
            sell_fee = fee_by_exchange.get(sell_book.exchange, Decimal("0"))
            top_size = min(buy_ask.amount, sell_bid.amount)
            if top_size <= 0:
                continue

            gross_spread_bps = ((sell_bid.price - buy_ask.price) / buy_ask.price) * Decimal("10000")
            buy_cost = buy_ask.price * (Decimal("1") + buy_fee)
            sell_proceeds = sell_bid.price * (Decimal("1") - sell_fee)
            net_spread = sell_proceeds - buy_cost
            net_spread_bps = (net_spread / buy_cost) * Decimal("10000")
            net_profit_quote = net_spread * top_size

            if net_spread_bps >= min_net_bps:
                opportunities.append(
                    Opportunity(
                        market=buy_book.market,
                        buy_exchange=buy_book.exchange,
                        sell_exchange=sell_book.exchange,
                        buy_ask=buy_ask.price,
                        sell_bid=sell_bid.price,
                        top_size=top_size,
                        gross_spread_bps=gross_spread_bps,
                        net_spread_bps=net_spread_bps,
                        net_profit_quote=net_profit_quote,
                    )
                )

    return sorted(opportunities, key=lambda item: item.net_spread_bps, reverse=True)
