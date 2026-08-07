from __future__ import annotations

import math
import statistics
from datetime import datetime
from typing import Any


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def daily_equity_points(equity_points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_day: dict[str, dict[str, Any]] = {}
    for point in equity_points:
        timestamp = _parse_datetime(point.get("recorded_at"))
        if timestamp is None:
            continue
        by_day[timestamp.date().isoformat()] = point

    daily: list[dict[str, Any]] = []
    previous_equity: float | None = None
    peak: float | None = None
    for day in sorted(by_day):
        source = by_day[day]
        equity = float(source.get("equity_jpy") or 0)
        daily_pnl = 0.0 if previous_equity is None else equity - previous_equity
        daily_return = (
            0.0 if previous_equity in {None, 0.0} else (equity / previous_equity) - 1.0
        )
        peak = equity if peak is None else max(peak, equity)
        drawdown = 0.0 if not peak else (equity / peak) - 1.0
        daily.append(
            {
                "date": day,
                "equity_jpy": equity,
                "daily_pnl_jpy": daily_pnl,
                "daily_return": daily_return,
                "drawdown": drawdown,
                "data_source": source.get("data_source"),
            }
        )
        previous_equity = equity
    return daily


def calculate_metrics(
    equity_points: list[dict[str, Any]], trades: list[dict[str, Any]]
) -> dict[str, Any]:
    daily = daily_equity_points(equity_points)
    if not daily:
        return {
            "initial_equity_jpy": 0.0,
            "current_equity_jpy": 0.0,
            "total_pnl_jpy": 0.0,
            "daily_pnl_jpy": 0.0,
            "total_return": 0.0,
            "annualized_return": None,
            "annualized_volatility": None,
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "max_drawdown": 0.0,
            "calmar_ratio": None,
            "win_rate": None,
            "profit_factor": None,
            "trade_count": 0,
            "fees_jpy": 0.0,
            "slippage_jpy": 0.0,
            "rebalance_reserve_jpy": 0.0,
            "daily": [],
        }

    initial = float(daily[0]["equity_jpy"])
    current = float(daily[-1]["equity_jpy"])
    total_pnl = current - initial
    total_return = 0.0 if initial == 0 else total_pnl / initial
    daily_pnl = float(daily[-1]["daily_pnl_jpy"])
    returns = [float(point["daily_return"]) for point in daily[1:]]

    mean_return = statistics.fmean(returns) if returns else None
    volatility = statistics.pstdev(returns) if len(returns) > 1 else None
    annualized_volatility = volatility * math.sqrt(365) if volatility else None
    sharpe = (
        mean_return / volatility * math.sqrt(365)
        if mean_return is not None and volatility
        else None
    )

    downside = [min(value, 0.0) for value in returns]
    downside_daily = (
        math.sqrt(statistics.fmean(value * value for value in downside)) if downside else None
    )
    downside_annual = downside_daily * math.sqrt(365) if downside_daily else None
    sortino = (
        mean_return * 365 / downside_annual
        if mean_return is not None and downside_annual
        else None
    )

    first_time = _parse_datetime(equity_points[0].get("recorded_at"))
    last_time = _parse_datetime(equity_points[-1].get("recorded_at"))
    elapsed_days = 0
    if first_time is not None and last_time is not None:
        elapsed_days = max((last_time.date() - first_time.date()).days, 0)
    annualized_return = None
    if elapsed_days > 0 and initial > 0 and current > 0:
        annualized_return = (current / initial) ** (365 / elapsed_days) - 1

    max_drawdown = min(float(point["drawdown"]) for point in daily)
    calmar = (
        annualized_return / abs(max_drawdown)
        if annualized_return is not None and max_drawdown < 0
        else None
    )

    pnls = [float(trade.get("net_pnl_jpy") or 0) for trade in trades]
    wins = [value for value in pnls if value > 0]
    losses = [value for value in pnls if value < 0]
    win_rate = len(wins) / len(pnls) if pnls else None
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss else None

    return {
        "initial_equity_jpy": initial,
        "current_equity_jpy": current,
        "total_pnl_jpy": total_pnl,
        "daily_pnl_jpy": daily_pnl,
        "total_return": total_return,
        "annualized_return": annualized_return,
        "annualized_volatility": annualized_volatility,
        "sharpe_ratio": sharpe,
        "sortino_ratio": sortino,
        "max_drawdown": max_drawdown,
        "calmar_ratio": calmar,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trade_count": len(trades),
        "fees_jpy": sum(float(trade.get("fees_jpy") or 0) for trade in trades),
        "slippage_jpy": sum(float(trade.get("slippage_jpy") or 0) for trade in trades),
        "rebalance_reserve_jpy": sum(
            float(trade.get("rebalance_reserve_jpy") or 0) for trade in trades
        ),
        "daily": daily,
    }
