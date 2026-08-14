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
    btc_amount = (initial_btc_value_jpy_per_exchange / reference_price).quantize(
        BTC_QUANTUM,
        rounding=ROUND_DOWN,
    )
    return {
        name: {"JPY": initial_jpy_per_exchange, "BTC": btc_amount}
        for name in exchange_names
    }


def _fee_map(exchange_configs: tuple[ExchangeConfig, ...]) -> dict[str, Decimal]:
    return {item.name: item.taker_fee_rate for item in exchange_configs}


def analyze_depth_route(
    buy_book: OrderBook,
    sell_book: OrderBook,
    exchange_configs: tuple[ExchangeConfig, ...],
    risk: PaperRiskConfig,
    *,
    available_jpy: Decimal | None = None,
    available_btc: Decimal | None = None,
    require_profitable_marginal: bool = False,
) -> dict[str, Any]:
    """Sweep matching ask/bid depth for one directed cross-venue route.

    The same BTC quantity is bought and sold.  Slippage is a conservative price
    buffer applied to each leg in addition to the observed order-book depth.
    """
    if buy_book.exchange == sell_book.exchange:
        raise ValueError("buy and sell exchanges must differ")

    fees = _fee_map(exchange_configs)
    buy_fee_rate = fees.get(buy_book.exchange, Decimal("0"))
    sell_fee_rate = fees.get(sell_book.exchange, Decimal("0"))
    slip = risk.slippage_bps / BPS
    cash_limit = available_jpy if available_jpy is not None else risk.max_trade_jpy
    cash_limit = min(cash_limit, risk.max_trade_jpy)
    inventory_limit = available_btc if available_btc is not None else Decimal("Infinity")

    ask_index = 0
    bid_index = 0
    ask_remaining = buy_book.asks[0].amount if buy_book.asks else Decimal("0")
    bid_remaining = sell_book.bids[0].amount if sell_book.bids else Decimal("0")
    quantity = Decimal("0")
    raw_buy = Decimal("0")
    raw_sell = Decimal("0")
    execution_buy = Decimal("0")
    execution_sell = Decimal("0")
    buy_levels: set[int] = set()
    sell_levels: set[int] = set()
    stopped_for_marginal = False

    while ask_index < len(buy_book.asks) and bid_index < len(sell_book.bids):
        ask = buy_book.asks[ask_index]
        bid = sell_book.bids[bid_index]
        effective_buy = ask.price * (Decimal("1") + slip)
        effective_sell = bid.price * (Decimal("1") - slip)
        marginal_cost = effective_buy * (Decimal("1") + buy_fee_rate)
        marginal_proceeds = effective_sell * (Decimal("1") - sell_fee_rate)
        if require_profitable_marginal and marginal_proceeds <= marginal_cost:
            stopped_for_marginal = True
            break

        remaining_inventory = inventory_limit - quantity
        remaining_cash = cash_limit - execution_buy * (Decimal("1") + buy_fee_rate)
        if remaining_inventory <= 0 or remaining_cash <= 0:
            break
        max_by_cash = remaining_cash / marginal_cost
        take = min(ask_remaining, bid_remaining, remaining_inventory, max_by_cash)
        take = take.quantize(BTC_QUANTUM, rounding=ROUND_DOWN)
        if take <= 0:
            break

        quantity += take
        raw_buy += ask.price * take
        raw_sell += bid.price * take
        execution_buy += effective_buy * take
        execution_sell += effective_sell * take
        buy_levels.add(ask_index)
        sell_levels.add(bid_index)
        ask_remaining -= take
        bid_remaining -= take

        if ask_remaining <= 0:
            ask_index += 1
            if ask_index < len(buy_book.asks):
                ask_remaining = buy_book.asks[ask_index].amount
        if bid_remaining <= 0:
            bid_index += 1
            if bid_index < len(sell_book.bids):
                bid_remaining = sell_book.bids[bid_index].amount

    first_ask = buy_book.best_ask.price if buy_book.best_ask else None
    first_bid = sell_book.best_bid.price if sell_book.best_bid else None
    if quantity <= 0:
        return {
            "market": buy_book.market,
            "buy_exchange": buy_book.exchange,
            "sell_exchange": sell_book.exchange,
            "first_ask_jpy": first_ask,
            "first_bid_jpy": first_bid,
            "quantity_btc": Decimal("0"),
            "buy_vwap_jpy": None,
            "sell_vwap_jpy": None,
            "buy_levels_consumed": 0,
            "sell_levels_consumed": 0,
            "gross_gap_jpy": (first_bid - first_ask) if first_bid is not None and first_ask is not None else None,
            "gross_spread_bps": None,
            "buy_notional_jpy": Decimal("0"),
            "sell_notional_jpy": Decimal("0"),
            "fees_jpy": Decimal("0"),
            "slippage_cost_jpy": Decimal("0"),
            "net_pnl_jpy": Decimal("0"),
            "net_spread_bps": None,
            "eligible": False,
            "reason": "限度額・在庫・板数量の条件で約定可能数量がありません",
            "stopped_for_marginal": stopped_for_marginal,
        }

    buy_vwap = raw_buy / quantity
    sell_vwap = raw_sell / quantity
    buy_fee = execution_buy * buy_fee_rate
    sell_fee = execution_sell * sell_fee_rate
    fees_jpy = buy_fee + sell_fee
    slippage_cost = (execution_buy - raw_buy) + (raw_sell - execution_sell)
    cash_required = execution_buy + buy_fee
    cash_received = execution_sell - sell_fee
    net_pnl = cash_received - cash_required
    net_bps = net_pnl / cash_required * BPS if cash_required else Decimal("0")
    gross_bps = (sell_vwap - buy_vwap) / buy_vwap * BPS if buy_vwap else Decimal("0")
    eligible = (
        raw_buy >= risk.min_trade_jpy
        and net_pnl > 0
        and net_bps >= risk.min_net_bps
    )
    if raw_buy < risk.min_trade_jpy:
        reason = "最低取引額未満"
    elif net_pnl <= 0:
        reason = "手数料・スリッページ後の損益がマイナス"
    elif net_bps < risk.min_net_bps:
        reason = "Netスプレッドが運用閾値未満"
    else:
        reason = "ペーパー執行条件を満たしています"

    return {
        "market": buy_book.market,
        "buy_exchange": buy_book.exchange,
        "sell_exchange": sell_book.exchange,
        "first_ask_jpy": first_ask,
        "first_bid_jpy": first_bid,
        "quantity_btc": quantity,
        "buy_vwap_jpy": buy_vwap,
        "sell_vwap_jpy": sell_vwap,
        "buy_levels_consumed": len(buy_levels),
        "sell_levels_consumed": len(sell_levels),
        "gross_gap_jpy": sell_vwap - buy_vwap,
        "gross_spread_bps": gross_bps,
        "buy_notional_jpy": raw_buy,
        "sell_notional_jpy": raw_sell,
        "execution_buy_jpy": execution_buy,
        "execution_sell_jpy": execution_sell,
        "cash_required_jpy": cash_required,
        "cash_received_jpy": cash_received,
        "fees_jpy": fees_jpy,
        "slippage_cost_jpy": slippage_cost,
        "net_pnl_jpy": net_pnl,
        "net_spread_bps": net_bps,
        "eligible": eligible,
        "reason": reason,
        "stopped_for_marginal": stopped_for_marginal,
    }


def analyze_all_routes(
    books: list[OrderBook],
    exchange_configs: tuple[ExchangeConfig, ...],
    balances: dict[str, dict[str, Decimal]],
    risk: PaperRiskConfig,
) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for buy_book in books:
        for sell_book in books:
            if buy_book.exchange == sell_book.exchange:
                continue
            buy_wallet = balances.get(buy_book.exchange, {})
            sell_wallet = balances.get(sell_book.exchange, {})
            routes.append(
                analyze_depth_route(
                    buy_book,
                    sell_book,
                    exchange_configs,
                    risk,
                    available_jpy=buy_wallet.get("JPY", Decimal("0")),
                    available_btc=sell_wallet.get("BTC", Decimal("0")),
                    require_profitable_marginal=False,
                )
            )
    return sorted(
        routes,
        key=lambda item: item.get("net_spread_bps")
        if item.get("net_spread_bps") is not None
        else Decimal("-Infinity"),
        reverse=True,
    )


def _apply_depth_trade(
    route: dict[str, Any],
    balances: dict[str, dict[str, Decimal]],
    *,
    timestamp: str,
) -> dict[str, Any]:
    buy_exchange = str(route["buy_exchange"])
    sell_exchange = str(route["sell_exchange"])
    quantity = Decimal(str(route["quantity_btc"]))
    cash_required = Decimal(str(route["cash_required_jpy"]))
    cash_received = Decimal(str(route["cash_received_jpy"]))
    buy_wallet = balances[buy_exchange]
    sell_wallet = balances[sell_exchange]
    buy_wallet["JPY"] -= cash_required
    buy_wallet["BTC"] += quantity
    sell_wallet["BTC"] -= quantity
    sell_wallet["JPY"] += cash_received
    compact = timestamp.replace("-", "").replace(":", "").replace("+", "p")
    return {
        "id": f"paper-{compact}-{buy_exchange}-{sell_exchange}",
        "timestamp": timestamp,
        "mode": "paper",
        "source": "public_orderbook_paper",
        "market": route["market"],
        "buy_exchange": buy_exchange,
        "sell_exchange": sell_exchange,
        "quantity_btc": quantity,
        "buy_price_jpy": route["buy_vwap_jpy"],
        "sell_price_jpy": route["sell_vwap_jpy"],
        "best_ask_jpy": route["first_ask_jpy"],
        "best_bid_jpy": route["first_bid_jpy"],
        "buy_notional_jpy": route["buy_notional_jpy"],
        "sell_notional_jpy": route["sell_notional_jpy"],
        "fees_jpy": route["fees_jpy"],
        "slippage_cost_jpy": route["slippage_cost_jpy"],
        "observed_gross_spread_bps": route["gross_spread_bps"],
        "execution_gross_spread_bps": route["gross_spread_bps"],
        "net_spread_bps": route["net_spread_bps"],
        "net_pnl_jpy": route["net_pnl_jpy"],
        "buy_levels_consumed": route["buy_levels_consumed"],
        "sell_levels_consumed": route["sell_levels_consumed"],
        "status": "filled",
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
    buy_wallet = balances.get(opportunity.buy_exchange)
    sell_wallet = balances.get(opportunity.sell_exchange)
    if buy_wallet is None or sell_wallet is None:
        return None, "missing_balance"
    route = analyze_depth_route(
        buy_book,
        sell_book,
        exchange_configs,
        risk,
        available_jpy=buy_wallet["JPY"],
        available_btc=sell_wallet["BTC"],
        require_profitable_marginal=True,
    )
    if not route["eligible"]:
        return None, str(route["reason"])
    return _apply_depth_trade(route, balances, timestamp=timestamp), "executed"


def execute_depth_route(
    route: dict[str, Any],
    balances: dict[str, dict[str, Decimal]],
    *,
    timestamp: str,
) -> tuple[dict[str, Any] | None, str]:
    if not route.get("eligible"):
        return None, str(route.get("reason") or "not_eligible")
    return _apply_depth_trade(route, balances, timestamp=timestamp), "executed"


def portfolio_equity(
    balances: dict[str, dict[str, Decimal]], reference_price: Decimal
) -> Decimal:
    return sum(
        (
            wallet.get("JPY", Decimal("0"))
            + wallet.get("BTC", Decimal("0")) * reference_price
            for wallet in balances.values()
        ),
        start=Decimal("0"),
    )


def calculate_pnl_attribution(
    balances: dict[str, dict[str, Decimal]],
    trades: list[dict[str, Any]],
    reference_price: Decimal,
    initial_capital_jpy: Decimal,
    initial_reference_price_jpy: Decimal,
    baseline: dict[str, Any] | None = None,
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    total_jpy = sum((wallet.get("JPY", Decimal("0")) for wallet in balances.values()), Decimal("0"))
    total_btc = sum((wallet.get("BTC", Decimal("0")) for wallet in balances.values()), Decimal("0"))
    all_trade_pnl = sum((Decimal(str(item.get("net_pnl_jpy", 0))) for item in trades), Decimal("0"))
    if baseline:
        initial_jpy = Decimal(str(baseline.get("initial_jpy_total", 0)))
        initial_btc = Decimal(str(baseline.get("initial_btc_total", total_btc)))
    else:
        initial_jpy = total_jpy - all_trade_pnl
        initial_btc = total_btc
    normalized_baseline = {
        "initial_jpy_total": initial_jpy,
        "initial_btc_total": initial_btc,
    }
    hold_value = initial_jpy + initial_btc * reference_price
    actual_equity = total_jpy + total_btc * reference_price
    strategy_pnl = actual_equity - hold_value
    inventory_mtm = initial_btc * (reference_price - initial_reference_price_jpy)
    total_equity_pnl = actual_equity - initial_capital_jpy
    seeded_realized = sum(
        (Decimal(str(item.get("net_pnl_jpy", 0))) for item in trades if item.get("source") == "seeded_demo"),
        Decimal("0"),
    )
    live_realized = sum(
        (Decimal(str(item.get("net_pnl_jpy", 0))) for item in trades if item.get("source") == "public_orderbook_paper"),
        Decimal("0"),
    )
    attribution = {
        "strategy_arbitrage_pnl_jpy": strategy_pnl,
        "inventory_mtm_pnl_jpy": inventory_mtm,
        "total_equity_pnl_jpy": total_equity_pnl,
        "hold_baseline_equity_jpy": hold_value,
        "seeded_demo_realized_pnl_jpy": seeded_realized,
        "live_public_realized_pnl_jpy": live_realized,
        "current_total_jpy": total_jpy,
        "current_total_btc": total_btc,
    }
    return attribution, normalized_baseline


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
    sortino = return_mean / downside_deviation * sqrt(365) if downside_deviation > 0 else None
    last_equity = daily_rows[-1]["equity_jpy"] if daily_rows else float(initial_capital_jpy)
    total_return = float(last_equity) / float(initial_capital_jpy) - 1.0
    periods = max(len(daily_rows) - 1, 1)
    growth = max(float(last_equity) / float(initial_capital_jpy), 0.000001)
    annualized_return = growth ** (365 / periods) - 1.0
    max_drawdown_pct = min((float(item["drawdown_pct"]) for item in daily_rows), default=0.0)
    calmar = annualized_return / abs(max_drawdown_pct / 100) if max_drawdown_pct < 0 else None
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
        "today_pnl_jpy": round(float(daily_rows[-1]["pnl_jpy"]) if daily_rows else 0.0, 2),
        "sharpe_ratio": round(sharpe, 4) if sharpe is not None else None,
        "sortino_ratio": round(sortino, 4) if sortino is not None else None,
        "calmar_ratio": round(calmar, 4) if calmar is not None else None,
        "annualized_volatility_pct": round(annualized_volatility, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "win_rate_pct": round(len(wins) / len(trade_pnls) * 100, 4) if trade_pnls else 0.0,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "trade_count": len(trades),
        "average_trade_pnl_jpy": round(fmean(trade_pnls) if trade_pnls else 0.0, 2),
        "fees_jpy": round(total_fees, 2),
        "slippage_jpy": round(total_slippage, 2),
        "best_day_jpy": round(max((float(item["pnl_jpy"]) for item in daily_rows), default=0.0), 2),
        "worst_day_jpy": round(min((float(item["pnl_jpy"]) for item in daily_rows), default=0.0), 2),
    }
    return metrics, daily_rows
