from decimal import Decimal

from arbscanner.models import ExchangeConfig, OrderBook, PriceLevel
from arbscanner.paper import (
    PaperRiskConfig,
    calculate_metrics,
    execute_opportunity,
    portfolio_equity,
)
from arbscanner.scanner import calculate_opportunities


def book(
    exchange: str,
    bid: str,
    ask: str,
    bid_size: str = "1",
    ask_size: str = "1",
) -> OrderBook:
    return OrderBook(
        exchange=exchange,
        market="BTC/JPY",
        raw_symbol="BTC_JPY",
        bids=(PriceLevel(Decimal(bid), Decimal(bid_size)),),
        asks=(PriceLevel(Decimal(ask), Decimal(ask_size)),),
    )


def exchange_config(name: str, fee_bps: str = "0") -> ExchangeConfig:
    return ExchangeConfig(
        name=name,
        enabled=True,
        pair="BTC_JPY",
        taker_fee_bps=Decimal(fee_bps),
    )


def test_executes_prefunded_arbitrage_and_updates_balances() -> None:
    books = [book("buy", "99", "100"), book("sell", "103", "104")]
    configs = (exchange_config("buy"), exchange_config("sell"))
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
    assert balances["buy"]["JPY"] < Decimal("1000")
    assert balances["buy"]["BTC"] > 0
    assert balances["sell"]["BTC"] < Decimal("1")
    assert portfolio_equity(balances, Decimal("101")) > Decimal("1000")


def test_rejects_opportunity_after_slippage() -> None:
    books = [book("buy", "99", "100"), book("sell", "101", "102")]
    configs = (exchange_config("buy"), exchange_config("sell"))
    opportunity = calculate_opportunities(books, configs)[0]
    balances = {
        "buy": {"JPY": Decimal("1000"), "BTC": Decimal("0")},
        "sell": {"JPY": Decimal("0"), "BTC": Decimal("1")},
    }
    risk = PaperRiskConfig(
        min_net_bps=Decimal("1"),
        max_trade_jpy=Decimal("500"),
        min_trade_jpy=Decimal("1"),
        slippage_bps=Decimal("100"),
    )

    trade, reason = execute_opportunity(
        opportunity,
        books,
        configs,
        balances,
        risk,
        timestamp="2026-08-07T12:00:00+09:00",
    )

    assert trade is None
    assert reason == "spread_below_risk_threshold"


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
