from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from math import sqrt
from statistics import fmean, pstdev
from typing import Any

from .models import ExchangeConfig, Opportunity, OrderBook

BTC_QUANTUM = Decimal("0.00000001")
MONEY_QUANTUM = Decimal("0.01")
BPS = Decimal("10000")


@dataclass(frozen=True)
class PaperRiskConfig:
    min_net_bps: Decimal = Decimal("5")
    max_trade_jpy: Decimal = Decimal("100000")
    min_trade_jpy: Decimal = Decimal("5000")
    slippage_bps: Decimal = Decimal("2")
    daily_loss_limit_jpy: Decimal = Decimal("50000")


def median_reference_price(books: list[OrderBook]) -> Decimal:
    mids: list[Decimal] = []
    for book in books:
        bid = book.best_bid
        ask = book.best_ask
        if bid is not None and ask is not None:
            mids.append((bid.price + ask.price) / Decimal("2"))
    if not mids:
        raise ValueError("no usable order books for reference price")
    ordered = sorted(mids)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def initialize_balances(
    exchange_names: list[str],
    reference_price: Decimal,
    *,
    initial_jpy_per_exchange: Decimal,
    initial_btc_value_jpy_per_exchange: Decimal,
) -> dict[str, dict[str, Decimal]]:
    if reference_price <= 0:
        raise ValueError("reference price must be positive")
    btc_amount = (
        initial_btc_value_jpy_per_exchange / reference_price
    ).quantize(BTC_QUANTUM, rounding=ROUND_DOWN)
    return {
        name: {
            "JPY": initial_jpy_per_exchange,
            "BTC": btc_amount,
        }
        for name in exchange_names
    }


def execute_opportunity(
    opportunity: Opportunity,
    books: list[OrderBook],
    exchange_configs: tuple[ExchangeConfig, ...],
    balances: dict[str, dict[str, Decimal]],
    risk: PaperRiskConfig,
    *,
    timestamp: str,
) -> tuple[dict[str, Any] | None, str]:
    books_by_exchange = {book.exchange: book for book in books}
    buy_book = books_by_exchange.get(opportunity.buy_exchange)
    sell_book = books_by_exchange.get(opportunity.sell_exchange)
    if buy_book is None or sell_book is None:
        return None, "missing_orderbook"

    best_ask = buy_book.best_ask
    best_bid = sell_book.best_bid
    if best_ask is None or best_bid is None:
        return None, "empty_orderbook"

    buy_wallet = balances.get(opportunity.buy_exchange)
    sell_wallet = balances.get(opportunity.sell_exchange)
    if buy_wallet is None or sell_wallet is None:
        return None, "missing_balance"

    fees = {item.name: item.taker_fee_rate for item in exchange_configs}
    buy_fee_rate = fees.get(opportunity.buy_exchange, Decimal("0"))
    sell_fee_rate = fees.get(opportunity.sell_exchange, Decimal("0"))
    slippage_rate = risk.slippage_bps / BPS

    buy_price = (best_ask.price * (Decimal("1") + slippage_rate)).quantize(
        MONEY_QUANTUM
    )
    sell_price = (best_bid.price * (Decimal("1") - slippage_rate)).quantize(
        MONEY_QUANTUM
    )

    max_by_cash = buy_wallet["JPY"] / (buy_price * (Decimal("1") + buy_fee_rate))
    max_by_inventory = sell_wallet["BTC"]
    max_by_risk = risk.max_trade_jpy / buy_price
    quantity = min(
        opportunity.top_size,
        max_by_cash,
        max_by_inventory,
        max_by_risk,
    ).quantize(BTC_QUANTUM, rounding=ROUND_DOWN)

    if quantity <= 0:
        return None, "insufficient_inventory"

    buy_notional = buy_price * quantity
    sell_notional = sell_price * quantity
    if buy_notional < risk.min_trade_jpy:
        return None, "below_min_trade"

    buy_fee = buy_notional * buy_fee_rate
    sell_fee = sell_notional * sell_fee_rate
    cash_required = buy_notional + buy_fee
    cash_received = sell_notional - sell_fee
    net_pnl = cash_received - cash_required
    net_bps = (net_pnl / cash_required) * BPS

    if net_bps < risk.min_net_bps:
        return None, "spread_below_risk_threshold"

    buy_wallet["JPY"] -= cash_required
    buy_wallet["BTC"] += quantity
    sell_wallet["BTC"] -= quantity
    sell_wallet["JPY"] += cash_received

    observed_slippage = (
        (buy_price - best_ask.price) * quantity
        + (best_bid.price - sell_price) * quantity
    )
    execution_gross_bps = ((sell_price - buy_price) / buy_price) * BPS
    compact_timestamp = (
        timestamp.replace("-", "").replace(":", "").replace("+", "p")
    )
    trade_id = (
        f"paper-{compact_timestamp}-{opportunity.buy_exchange}-"
        f"{opportunity.sell_exchange}"
    )

    return (
        {
            "id": trade_id,
            "timestamp": timestamp,
            "mode": "paper",
            "source": "public_orderbook_paper",
            "market": opportunity.market,
            "buy_exchange": opportunity.buy_exchange,
            "sell_exchange": opportunity.sell_exchange,
            "quantity_btc": quantity,
            "buy_price_jpy": buy_price,
            "sell_price_jpy": sell_price,
            "buy_notional_jpy": buy_notional,
            "sell_notional_jpy": sell_notional,
            "fees_jpy": buy_fee + sell_fee,
            "slippage_cost_jpy": observed_slippage,
            "observed_gross_spread_bps": opportunity.gross_spread_bps,
            "execution_gross_spread_bps": execution_gross_bps,
            "net_spread_bps": net_bps,
            "net_pnl_jpy": net_pnl,
            "status": "filled",
        },
        "executed",
    )


def portfolio_equity(
    balances: dict[str, dict[str, Decimal]],
    reference_price: Decimal,
) -> Decimal:
    return sum(
        (
            wallet.get("JPY", Decimal("0"))
            + wallet.get("BTC", Decimal("0")) * reference_price
            for wallet in balances.values()
        ),
        start=Decimal("0"),
    )


def calculate_metrics(
    equity_history: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    initial_capital_jpy: Decimal,
) -> tuple[dict[str, float | int | None], list[dict[str, float | str]]]:
    if initial_capital_jpy <= 0:
        raise ValueError("initial capital must be positive")

    daily_last: dict[str, float] = {}
    for point in sorted(equity_history, key=lambda item: str(item["timestamp"])):
        daily_last[str(point["timestamp"])[:10]] = float(point["equity_jpy"])

    previous = float(initial_capital_jpy)
    peak = previous
    returns: list[float] = []
    daily_rows: list[dict[str, float | str]] = []
    for date, equity in sorted(daily_last.items()):
        pnl = equity - previous
        daily_return = pnl / previous if previous else 0.0
        peak = max(peak, equity)
        drawdown_pct = ((equity / peak) - 1.0) * 100 if peak else 0.0
        daily_rows.append(
            {
                "date": date,
                "equity_jpy": round(equity, 2),
                "pnl_jpy": round(pnl, 2),
                "return_pct": round(daily_return * 100, 6),
                "drawdown_pct": round(drawdown_pct, 6),
            }
        )
        returns.append(daily_return)
        previous = equity

    usable_returns = returns[1:] if len(returns) > 1 else returns
    return_mean = fmean(usable_returns) if usable_returns else 0.0
    return_std = pstdev(usable_returns) if len(usable_returns) > 1 else 0.0
    sharpe = return_mean / return_std * sqrt(365) if return_std > 0 else None

    downside_squares = [min(item, 0.0) ** 2 for item in usable_returns]
    downside_deviation = sqrt(fmean(downside_squares)) if downside_squares else 0.0
    sortino = (
        return_mean / downside_deviation * sqrt(365)
        if downside_deviation > 0
        else None
    )

    last_equity = daily_rows[-1]["equity_jpy"] if daily_rows else float(initial_capital_jpy)
    total_return = float(last_equity) / float(initial_capital_jpy) - 1.0
    periods = max(len(daily_rows) - 1, 1)
    growth = max(float(last_equity) / float(initial_capital_jpy), 0.000001)
    annualized_return = growth ** (365 / periods) - 1.0
    max_drawdown_pct = min(
        (float(item["drawdown_pct"]) for item in daily_rows),
        default=0.0,
    )
    calmar = (
        annualized_return / abs(max_drawdown_pct / 100)
        if max_drawdown_pct < 0
        else None
    )
    annualized_volatility = return_std * sqrt(365) * 100

    trade_pnls = [float(item.get("net_pnl_jpy", 0)) for item in trades]
    wins = [item for item in trade_pnls if item > 0]
    losses = [item for item in trade_pnls if item < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    realized_pnl = sum(trade_pnls)
    total_pnl = float(last_equity) - float(initial_capital_jpy)
    total_fees = sum(float(item.get("fees_jpy", 0)) for item in trades)
    total_slippage = sum(float(item.get("slippage_cost_jpy", 0)) for item in trades)

    metrics: dict[str, float | int | None] = {
        "portfolio_value_jpy": round(float(last_equity), 2),
        "initial_capital_jpy": round(float(initial_capital_jpy), 2),
        "total_pnl_jpy": round(total_pnl, 2),
        "realized_pnl_jpy": round(realized_pnl, 2),
        "unrealized_pnl_jpy": round(total_pnl - realized_pnl, 2),
        "total_return_pct": round(total_return * 100, 6),
        "annualized_return_pct": round(annualized_return * 100, 6),
        "today_pnl_jpy": round(
            float(daily_rows[-1]["pnl_jpy"]) if daily_rows else 0.0,
            2,
        ),
        "sharpe_ratio": round(sharpe, 4) if sharpe is not None else None,
        "sortino_ratio": round(sortino, 4) if sortino is not None else None,
        "calmar_ratio": round(calmar, 4) if calmar is not None else None,
        "annualized_volatility_pct": round(annualized_volatility, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "win_rate_pct": round(len(wins) / len(trade_pnls) * 100, 4)
        if trade_pnls
        else 0.0,
        "profit_factor": round(profit_factor, 4)
        if profit_factor is not None
        else None,
        "trade_count": len(trades),
        "average_trade_pnl_jpy": round(
            fmean(trade_pnls) if trade_pnls else 0.0,
            2,
        ),
        "fees_jpy": round(total_fees, 2),
        "slippage_jpy": round(total_slippage, 2),
        "best_day_jpy": round(
            max((float(item["pnl_jpy"]) for item in daily_rows), default=0.0),
            2,
        ),
        "worst_day_jpy": round(
            min((float(item["pnl_jpy"]) for item in daily_rows), default=0.0),
            2,
        ),
    }
    return metrics, daily_rows
