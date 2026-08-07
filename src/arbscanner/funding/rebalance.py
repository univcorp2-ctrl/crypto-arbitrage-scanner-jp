from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .models import decimal_value


@dataclass(frozen=True, slots=True)
class CapitalState:
    spot_jpy: Decimal
    spot_btc: Decimal
    collateral_jpy: Decimal
    btc_price_jpy: Decimal


@dataclass(frozen=True, slots=True)
class RebalanceParameters:
    target_notional_jpy: Decimal
    max_leverage: Decimal = Decimal("2")
    margin_buffer_ratio: Decimal = Decimal("1.8")
    spot_cash_buffer_bps: Decimal = Decimal("40")


@dataclass(frozen=True, slots=True)
class RebalanceStep:
    action: str
    amount_jpy: Decimal
    automatic: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "amount_jpy": float(self.amount_jpy),
            "automatic": self.automatic,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class RebalancePlan:
    feasible_notional_jpy: Decimal
    target_notional_jpy: Decimal
    ready: bool
    required_spot_jpy: Decimal
    required_collateral_jpy: Decimal
    steps: tuple[RebalanceStep, ...]
    automatic_withdrawals: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "feasible_notional_jpy": float(self.feasible_notional_jpy),
            "target_notional_jpy": float(self.target_notional_jpy),
            "ready": self.ready,
            "required_spot_jpy": float(self.required_spot_jpy),
            "required_collateral_jpy": float(self.required_collateral_jpy),
            "steps": [step.to_dict() for step in self.steps],
            "automatic_withdrawals": self.automatic_withdrawals,
        }


def plan_rebalance(state: CapitalState, parameters: RebalanceParameters) -> RebalancePlan:
    if parameters.max_leverage <= 0 or parameters.margin_buffer_ratio < 1:
        raise ValueError("invalid leverage or margin buffer")
    if parameters.target_notional_jpy <= 0:
        raise ValueError("target_notional_jpy must be positive")

    spot_multiplier = Decimal("1") + parameters.spot_cash_buffer_bps / Decimal("10000")
    required_spot = parameters.target_notional_jpy * spot_multiplier
    required_collateral = (
        parameters.target_notional_jpy
        / parameters.max_leverage
        * parameters.margin_buffer_ratio
    )
    feasible_from_spot = state.spot_jpy / spot_multiplier
    feasible_from_collateral = (
        state.collateral_jpy * parameters.max_leverage / parameters.margin_buffer_ratio
    )
    feasible = max(Decimal("0"), min(feasible_from_spot, feasible_from_collateral))

    steps: list[RebalanceStep] = []
    spot_shortfall = max(Decimal("0"), required_spot - state.spot_jpy)
    collateral_shortfall = max(Decimal("0"), required_collateral - state.collateral_jpy)
    if spot_shortfall:
        steps.append(
            RebalanceStep(
                action="ADD_SPOT_ACCOUNT_JPY",
                amount_jpy=spot_shortfall,
                automatic=False,
                reason="Pre-fund the spot purchase leg. External withdrawals are disabled.",
            )
        )
    if collateral_shortfall:
        steps.append(
            RebalanceStep(
                action="ADD_CFD_COLLATERAL_JPY",
                amount_jpy=collateral_shortfall,
                automatic=False,
                reason="Increase margin buffer before opening the derivative leg.",
            )
        )
    if not steps:
        steps.append(
            RebalanceStep(
                action="NO_TRANSFER_REQUIRED",
                amount_jpy=Decimal("0"),
                automatic=False,
                reason="Both legs are already pre-funded.",
            )
        )
    return RebalancePlan(
        feasible_notional_jpy=feasible,
        target_notional_jpy=parameters.target_notional_jpy,
        ready=not spot_shortfall and not collateral_shortfall,
        required_spot_jpy=required_spot,
        required_collateral_jpy=required_collateral,
        steps=tuple(steps),
    )


def state_from_mapping(values: dict[str, Any]) -> CapitalState:
    return CapitalState(
        spot_jpy=decimal_value(values.get("spot_jpy", 0)),
        spot_btc=decimal_value(values.get("spot_btc", 0)),
        collateral_jpy=decimal_value(values.get("collateral_jpy", 0)),
        btc_price_jpy=decimal_value(values.get("btc_price_jpy", 0)),
    )
