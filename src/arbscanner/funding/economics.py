from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from .models import BPS, EconomicsResult, FundingSnapshot, Side, StrategyParameters, utc_now

JST = ZoneInfo("Asia/Tokyo")
MIN_BITFLYER_ORDER_BTC = Decimal("0.001")


def _in_bitflyer_maintenance_window(at: datetime) -> bool:
    local = at.astimezone(JST)
    return local.hour == 4 and local.minute < 10


def evaluate_opportunity(
    snapshot: FundingSnapshot,
    parameters: StrategyParameters,
    *,
    now: datetime | None = None,
) -> EconomicsResult:
    """Evaluate a conservative delta-neutral funding trade.

    Positive funding is modeled as long spot / short Crypto CFD. Positive entry basis is
    intentionally ignored as profit; negative entry basis is charged as a cost. Negative
    funding requires an explicitly enabled inventory-short hedge because ordinary spot cannot
    create a naked short position.
    """

    parameters.validate()
    selected_now = now or utc_now()
    interval_hours = max(snapshot.funding_interval_hours, Decimal("0.0001"))
    intervals = max(1, math.ceil(float(parameters.hold_hours / interval_hours)))
    rate_bps = snapshot.funding_rate * BPS

    derivative_side: Side | None
    spot_side: Side | None
    hedge_supported = True
    if rate_bps > 0:
        derivative_side = Side.SELL
        spot_side = Side.BUY
        executable_basis_bps = (
            (snapshot.derivative_bid / snapshot.spot_ask) - Decimal("1")
        ) * BPS
        action = "BUY_SPOT_SELL_CFD"
    elif rate_bps < 0:
        derivative_side = Side.BUY
        spot_side = Side.SELL
        executable_basis_bps = (
            (snapshot.spot_bid / snapshot.derivative_ask) - Decimal("1")
        ) * BPS
        action = "SELL_INVENTORY_BUY_CFD"
        hedge_supported = parameters.allow_negative_rate_inventory_hedge
    else:
        derivative_side = None
        spot_side = None
        executable_basis_bps = Decimal("0")
        action = "NO_TRADE"
        hedge_supported = False

    funding_income_bps = abs(rate_bps) * Decimal(intervals)
    leverage_cost_bps = parameters.leverage_point_daily_bps * (
        parameters.hold_hours / Decimal("24")
    )
    trading_cost_bps = (
        parameters.spot_taker_fee_bps * Decimal("2")
        + parameters.derivative_taker_fee_bps * Decimal("2")
    )
    slippage_cost_bps = parameters.slippage_bps_per_fill * Decimal("4")
    adverse_entry_basis_bps = max(Decimal("0"), -executable_basis_bps)
    basis_cost_bps = adverse_entry_basis_bps + parameters.basis_exit_buffer_bps
    total_cost_bps = (
        leverage_cost_bps
        + trading_cost_bps
        + slippage_cost_bps
        + basis_cost_bps
        + parameters.risk_buffer_bps
    )
    net_bps = funding_income_bps - total_cost_bps
    break_even = total_cost_bps / Decimal(intervals)
    position_size = parameters.notional_jpy / max(snapshot.spot_ask, Decimal("1"))
    expected_pnl = parameters.notional_jpy * net_bps / BPS
    annualization_periods = Decimal("365") * Decimal("24") / parameters.hold_hours
    annualized_return_pct = net_bps / BPS * annualization_periods * Decimal("100")

    reasons: list[str] = []
    if snapshot.funding_rate == 0:
        reasons.append("funding_rate_is_zero")
    if not hedge_supported:
        reasons.append("hedge_direction_not_supported_for_japan_spot_profile")
    if snapshot.age_seconds(selected_now) > parameters.max_data_age_seconds:
        reasons.append("market_data_is_stale")
    if snapshot.spot_health != "NORMAL" or snapshot.derivative_health != "NORMAL":
        reasons.append("venue_health_is_not_normal")
    if abs(snapshot.basis_bps) > parameters.max_abs_basis_bps:
        reasons.append("absolute_basis_exceeds_limit")
    if position_size < MIN_BITFLYER_ORDER_BTC:
        reasons.append("position_below_exchange_minimum")
    if position_size > parameters.max_order_btc:
        reasons.append("position_exceeds_order_limit")
    if _in_bitflyer_maintenance_window(selected_now):
        reasons.append("bitflyer_maintenance_window")
    if snapshot.next_settlement <= selected_now:
        reasons.append("next_settlement_is_not_in_the_future")
    if net_bps < parameters.min_expected_net_bps:
        reasons.append("expected_net_bps_below_threshold")

    accepted = not reasons
    return EconomicsResult(
        accepted=accepted,
        action=action if accepted else "NO_TRADE",
        derivative_side=derivative_side,
        spot_side=spot_side,
        intervals=intervals,
        position_size_btc=position_size,
        funding_income_bps=funding_income_bps,
        leverage_cost_bps=leverage_cost_bps,
        trading_cost_bps=trading_cost_bps,
        slippage_cost_bps=slippage_cost_bps,
        basis_cost_bps=basis_cost_bps,
        risk_buffer_bps=parameters.risk_buffer_bps,
        net_bps=net_bps,
        break_even_rate_bps_per_interval=break_even,
        expected_pnl_jpy=expected_pnl,
        annualized_return_pct=annualized_return_pct,
        executable_basis_bps=executable_basis_bps,
        rejection_reasons=tuple(reasons),
    )
