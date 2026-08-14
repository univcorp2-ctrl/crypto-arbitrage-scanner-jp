from decimal import Decimal

from arbscanner.models import ExchangeConfig, OrderBook, PriceLevel
from arbscanner.paper_ledger import (
    PaperRiskConfig,
    analyze_depth_route,
    calculate_pnl_attribution,
)


def book(exchange: str, bids: list[tuple[str, str]], asks: list[tuple[str, str]]) -> OrderBook:
    return OrderBook(
        exchange=exchange,
        market="BTC/JPY",
        raw_symbol="BTC_JPY",
        bids=tuple(PriceLevel(Decimal(p), Decimal(q)) for p, q in bids),
        asks=tuple(PriceLevel(Decimal(p), Decimal(q)) for p, q in asks),
    )


def configs() -> tuple[ExchangeConfig, ...]:
    return (
        ExchangeConfig("buy", True, "BTC_JPY", Decimal("0")),
        ExchangeConfig("sell", True, "BTC_JPY", Decimal("0")),
    )


def test_depth_route_sweeps_multiple_levels_and_uses_vwap() -> None:
    buy = book("buy", [("99", "10")], [("100", "1"), ("101", "2")])
    sell = book("sell", [("105", "1"), ("104", "2")], [("106", "10")])
    risk = PaperRiskConfig(
        min_net_bps=Decimal("0"),
        max_trade_jpy=Decimal("250"),
        min_trade_jpy=Decimal("1"),
        slippage_bps=Decimal("0"),
    )
    route = analyze_depth_route(
        buy,
        sell,
        configs(),
        risk,
        available_jpy=Decimal("1000"),
        available_btc=Decimal("10"),
    )
    assert route["quantity_btc"] > Decimal("2")
    assert route["buy_levels_consumed"] == 2
    assert route["sell_levels_consumed"] == 2
    assert route["buy_vwap_jpy"] > Decimal("100")
    assert route["sell_vwap_jpy"] < Decimal("105")
    assert route["net_pnl_jpy"] > 0
    assert route["eligible"] is True


def test_unprofitable_route_is_not_eligible() -> None:
    buy = book("buy", [("99", "1")], [("105", "1")])
    sell = book("sell", [("100", "1")], [("101", "1")])
    risk = PaperRiskConfig(min_net_bps=Decimal("1"), min_trade_jpy=Decimal("1"))
    route = analyze_depth_route(
        buy,
        sell,
        configs(),
        risk,
        available_jpy=Decimal("1000"),
        available_btc=Decimal("1"),
    )
    assert route["net_pnl_jpy"] < 0
    assert route["eligible"] is False


def test_inventory_and_cash_limit_quantity() -> None:
    buy = book("buy", [("99", "10")], [("100", "10")])
    sell = book("sell", [("103", "10")], [("104", "10")])
    risk = PaperRiskConfig(
        min_net_bps=Decimal("0"),
        max_trade_jpy=Decimal("10000"),
        min_trade_jpy=Decimal("1"),
        slippage_bps=Decimal("0"),
    )
    by_inventory = analyze_depth_route(
        buy,
        sell,
        configs(),
        risk,
        available_jpy=Decimal("10000"),
        available_btc=Decimal("0.5"),
    )
    assert by_inventory["quantity_btc"] == Decimal("0.50000000")
    by_cash = analyze_depth_route(
        buy,
        sell,
        configs(),
        risk,
        available_jpy=Decimal("25"),
        available_btc=Decimal("10"),
    )
    assert by_cash["quantity_btc"] == Decimal("0.25000000")


def test_pnl_attribution_separates_inventory_move_from_strategy() -> None:
    balances = {
        "a": {"JPY": Decimal("510"), "BTC": Decimal("1")},
        "b": {"JPY": Decimal("500"), "BTC": Decimal("1")},
    }
    trades = [{"source": "public_orderbook_paper", "net_pnl_jpy": Decimal("10")}]
    attribution, baseline = calculate_pnl_attribution(
        balances,
        trades,
        reference_price=Decimal("90"),
        initial_capital_jpy=Decimal("1200"),
        initial_reference_price_jpy=Decimal("100"),
    )
    assert baseline["initial_jpy_total"] == Decimal("1000")
    assert baseline["initial_btc_total"] == Decimal("2")
    assert attribution["strategy_arbitrage_pnl_jpy"] == Decimal("10")
    assert attribution["inventory_mtm_pnl_jpy"] == Decimal("-20")
    assert attribution["total_equity_pnl_jpy"] == Decimal("-10")
