from __future__ import annotations

from decimal import Decimal

from arbscanner.models import ExchangeConfig, Opportunity
from arbscanner.paper import PaperSettings, plan_paper_trade


def opportunity() -> Opportunity:
    return Opportunity(
        market="BTC/JPY",
        buy_exchange="buy",
        sell_exchange="sell",
        buy_ask=Decimal("100"),
        sell_bid=Decimal("103"),
        top_size=Decimal("100"),
        gross_spread_bps=Decimal("300"),
        net_spread_bps=Decimal("280"),
        net_profit_quote=Decimal("300"),
    )


def configs() -> tuple[ExchangeConfig, ...]:
    return (
        ExchangeConfig("buy", True, "BTC_JPY", Decimal("10")),
        ExchangeConfig("sell", True, "BTC_JPY", Decimal("10")),
    )


def test_plan_paper_trade_respects_cash_inventory_and_costs() -> None:
    settings = PaperSettings(
        min_net_bps=Decimal("5"),
        max_trade_jpy=Decimal("5000"),
        min_trade_jpy=Decimal("100"),
        slippage_bps=Decimal("2"),
        rebalance_reserve_bps=Decimal("3"),
        autostart=False,
    )
    balances = {
        ("buy", "JPY"): Decimal("10000"),
        ("buy", "BTC"): Decimal("0"),
        ("sell", "JPY"): Decimal("0"),
        ("sell", "BTC"): Decimal("10"),
    }

    plan = plan_paper_trade(opportunity(), configs(), balances, settings)

    assert plan is not None
    assert plan["net_pnl_jpy"] > 0
    assert plan["buy_debit_jpy"] <= 10000
    assert plan["quantity_btc"] <= 10


def test_plan_paper_trade_requires_prefunded_sell_inventory() -> None:
    settings = PaperSettings(min_trade_jpy=Decimal("100"), autostart=False)
    balances = {
        ("buy", "JPY"): Decimal("10000"),
        ("sell", "BTC"): Decimal("0"),
    }

    assert plan_paper_trade(opportunity(), configs(), balances, settings) is None
