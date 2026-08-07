from decimal import Decimal

from arbscanner.models import ExchangeConfig, OrderBook, PriceLevel
from arbscanner.paper_ledger import (
    PaperRiskConfig,
    calculate_metrics,
    execute_opportunity,
    initialize_balances,
    median_reference_price,
    portfolio_equity,
)
from arbscanner.scanner import calculate_opportunities


def book(exchange: str, bid: str, ask: str, size: str = "1") -> OrderBook:
    return OrderBook(
        exchange=exchange,
        market="BTC/JPY",
        raw_symbol="BTC_JPY",
        bids=(PriceLevel(Decimal(bid), Decimal(size)),),
        asks=(PriceLevel(Decimal(ask), Decimal(size)),),
    )


def config(name: str, fee_bps: str = "0") -> ExchangeConfig:
    return ExchangeConfig(name, True, "BTC_JPY", Decimal(fee_bps))


def test_reference_price_and_balances() -> None:
    books = [book("one", "99", "101"), book("two", "103", "105")]
    reference = median_reference_price(books)
    balances = initialize_balances(
        ["one", "two"],
        reference,
        initial_jpy_per_exchange=Decimal("1000"),
        initial_btc_value_jpy_per_exchange=Decimal("1000"),
    )
    assert reference == Decimal("102")
    assert balances["one"]["JPY"] == Decimal("1000")
    assert balances["one"]["BTC"] > 0


def test_executes_prefunded_cross_venue_paper_trade() -> None:
    books = [book("buy", "99", "100"), book("sell", "103", "104")]
    configs = (config("buy"), config("sell"))
    opportunity = calculate_opportunities(books, configs)[0]
    balances = {
        "buy": {"JPY": Decimal("1000"), "BTC": Decimal("0")},
        "sell": {"JPY": Decimal("0"), "BTC": Decimal("1")},
    }
    risk = PaperRiskConfig(
        min_net_bps=Decimal("0"),
        max_trade_jpy=Decimal("500"),
        min_trade_jpy=Decimal("1"),
        slippage_bps=Decimal("0"),
    )

    trade, reason = execute_opportunity(
        opportunity,
        books,
        configs,
        balances,
        risk,
        timestamp="2026-08-07T12:00:00+09:00",
    )

    assert reason == "executed"
    assert trade is not None
    assert trade["net_pnl_jpy"] > 0
    assert balances["buy"]["BTC"] > 0
    assert balances["sell"]["BTC"] < 1
    assert portfolio_equity(balances, Decimal("101")) > Decimal("1000")


def test_metrics_include_drawdown_and_trade_statistics() -> None:
    history = [
        {"timestamp": "2026-08-01T00:00:00+09:00", "equity_jpy": 100},
        {"timestamp": "2026-08-02T00:00:00+09:00", "equity_jpy": 90},
        {"timestamp": "2026-08-03T00:00:00+09:00", "equity_jpy": 110},
    ]
    trades = [
        {"net_pnl_jpy": 4, "fees_jpy": 1, "slippage_cost_jpy": 0.5},
        {"net_pnl_jpy": -2, "fees_jpy": 1, "slippage_cost_jpy": 0.5},
    ]

    metrics, daily = calculate_metrics(history, trades, Decimal("100"))

    assert metrics["total_return_pct"] == 10.0
    assert metrics["max_drawdown_pct"] == -10.0
    assert metrics["win_rate_pct"] == 50.0
    assert metrics["profit_factor"] == 2.0
    assert len(daily) == 3
