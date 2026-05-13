from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .config import ScannerConfig, load_config
from .models import Opportunity, OrderBook
from .scanner import calculate_opportunities, fetch_orderbooks


def main() -> None:
    args = _parse_args()
    config = load_config(args.config)
    if args.market:
        config = ScannerConfig(
            market=args.market,
            min_net_bps=config.min_net_bps,
            request_timeout_seconds=config.request_timeout_seconds,
            exchanges=config.exchanges,
        )
    min_net_bps = Decimal(str(args.min_net_bps)) if args.min_net_bps is not None else config.min_net_bps

    if args.watch and args.watch > 0:
        asyncio.run(_watch(config, min_net_bps=min_net_bps, seconds=args.watch))
    else:
        asyncio.run(_scan_once(config, min_net_bps=min_net_bps))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only arbitrage scanner for public crypto exchange order books."
    )
    parser.add_argument("--config", default="config.yml", type=Path, help="Path to YAML config.")
    parser.add_argument("--market", help="Market label to show in output, for example BTC/JPY.")
    parser.add_argument(
        "--min-net-bps",
        type=str,
        help="Minimum net spread in basis points after configured taker fees.",
    )
    parser.add_argument(
        "--watch",
        type=float,
        default=0,
        help="Repeat scan every N seconds. Omit or set 0 to run once.",
    )
    return parser.parse_args()


async def _watch(config: ScannerConfig, *, min_net_bps: Decimal, seconds: float) -> None:
    while True:
        await _scan_once(config, min_net_bps=min_net_bps)
        await asyncio.sleep(seconds)


async def _scan_once(config: ScannerConfig, *, min_net_bps: Decimal) -> None:
    books, errors = await fetch_orderbooks(config)
    opportunities = calculate_opportunities(books, config.exchanges, min_net_bps=min_net_bps)
    _print_result(config.market, books, opportunities, errors, min_net_bps=min_net_bps)


def _print_result(
    market: str,
    books: list[OrderBook],
    opportunities: list[Opportunity],
    errors: dict[str, str],
    *,
    min_net_bps: Decimal,
) -> None:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    print(f"\n[{now}] market={market} min_net_bps={_fmt(min_net_bps)}")

    print("\nOrder books")
    print("exchange      bid             bid_size        ask             ask_size")
    print("------------  --------------  --------------  --------------  --------------")
    for book in sorted(books, key=lambda item: item.exchange):
        bid = book.best_bid
        ask = book.best_ask
        if bid is None or ask is None:
            continue
        print(
            f"{book.exchange:<12}  "
            f"{_fmt(bid.price):>14}  {_fmt(bid.amount):>14}  "
            f"{_fmt(ask.price):>14}  {_fmt(ask.amount):>14}"
        )

    if errors:
        print("\nErrors")
        for exchange, message in sorted(errors.items()):
            print(f"- {exchange}: {message}")

    print("\nOpportunities")
    if not opportunities:
        print("No opportunities above threshold.")
        return

    print(
        "buy@exchange  sell@exchange  buy_ask         sell_bid        "
        "top_size       gross_bps      net_bps        net_profit_quote"
    )
    print(
        "------------  -------------  --------------  --------------  "
        "-------------  -------------  -------------  ----------------"
    )
    for item in opportunities:
        print(
            f"{item.buy_exchange:<12}  {item.sell_exchange:<13}  "
            f"{_fmt(item.buy_ask):>14}  {_fmt(item.sell_bid):>14}  "
            f"{_fmt(item.top_size):>13}  {_fmt(item.gross_spread_bps):>13}  "
            f"{_fmt(item.net_spread_bps):>13}  {_fmt(item.net_profit_quote):>16}"
        )


def _fmt(value: Decimal) -> str:
    normalized = value.quantize(Decimal("0.00000001"))
    return format(normalized.normalize(), "f")


if __name__ == "__main__":
    main()
