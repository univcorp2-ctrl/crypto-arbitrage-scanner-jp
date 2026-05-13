from decimal import Decimal

from arbscanner.models import ExchangeConfig, OrderBook, PriceLevel
from arbscanner.scanner import calculate_opportunities


def book(exchange: str, bid: str, ask: str, bid_size: str = "1", ask_size: str = "1") -> OrderBook:
    return OrderBook(
        exchange=exchange,
        market="BTC/JPY",
        raw_symbol="BTC_JPY",
        bids=(PriceLevel(Decimal(bid), Decimal(bid_size)),),
        asks=(PriceLevel(Decimal(ask), Decimal(ask_size)),),
    )


def config(name: str, fee_bps: str) -> ExchangeConfig:
    return ExchangeConfig(name=name, enabled=True, pair="BTC_JPY", taker_fee_bps=Decimal(fee_bps))


def test_calculates_profitable_opportunity_after_fees() -> None:
    books = [book("a", bid="99", ask="100"), book("b", bid="102", ask="103")]
    configs = (config("a", "10"), config("b", "10"))

    opportunities = calculate_opportunities(books, configs, min_net_bps=Decimal("0"))

    assert len(opportunities) == 1
    item = opportunities[0]
    assert item.buy_exchange == "a"
    assert item.sell_exchange == "b"
    assert item.net_spread_bps > Decimal("0")


def test_filters_below_threshold() -> None:
    books = [book("a", bid="99", ask="100"), book("b", bid="100.05", ask="101")]
    configs = (config("a", "10"), config("b", "10"))

    opportunities = calculate_opportunities(books, configs, min_net_bps=Decimal("5"))

    assert opportunities == []


def test_top_size_is_minimum_of_best_levels() -> None:
    books = [
        book("a", bid="99", ask="100", ask_size="0.25"),
        book("b", bid="103", ask="104", bid_size="0.5"),
    ]
    configs = (config("a", "0"), config("b", "0"))

    opportunities = calculate_opportunities(books, configs)

    assert opportunities[0].top_size == Decimal("0.25")
