from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

BPS = Decimal("10000")


def decimal_value(value: Decimal | int | float | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class AutomationMode(StrEnum):
    PAPER = "paper"
    SHADOW = "shadow"
    LIVE = "live"


class OrderState(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FundingRatePoint:
    rate: Decimal
    calculation_date: datetime
    settlement_date: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "rate": float(self.rate),
            "calculation_date": self.calculation_date.isoformat(),
            "settlement_date": self.settlement_date.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class FundingSnapshot:
    venue: str
    symbol: str
    funding_rate: Decimal
    funding_interval_hours: Decimal
    next_settlement: datetime
    spot_bid: Decimal
    spot_ask: Decimal
    derivative_bid: Decimal
    derivative_ask: Decimal
    captured_at: datetime
    spot_health: str = "NORMAL"
    derivative_health: str = "NORMAL"

    @property
    def spot_mid(self) -> Decimal:
        return (self.spot_bid + self.spot_ask) / Decimal("2")

    @property
    def derivative_mid(self) -> Decimal:
        return (self.derivative_bid + self.derivative_ask) / Decimal("2")

    @property
    def basis_bps(self) -> Decimal:
        if self.spot_mid <= 0:
            return Decimal("0")
        return ((self.derivative_mid / self.spot_mid) - Decimal("1")) * BPS

    def age_seconds(self, now: datetime | None = None) -> Decimal:
        selected_now = now or utc_now()
        return decimal_value(max(0.0, (selected_now - self.captured_at).total_seconds()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "symbol": self.symbol,
            "funding_rate": float(self.funding_rate),
            "funding_interval_hours": float(self.funding_interval_hours),
            "next_settlement": self.next_settlement.isoformat(),
            "spot": {
                "bid": float(self.spot_bid),
                "ask": float(self.spot_ask),
                "mid": float(self.spot_mid),
                "health": self.spot_health,
            },
            "derivative": {
                "bid": float(self.derivative_bid),
                "ask": float(self.derivative_ask),
                "mid": float(self.derivative_mid),
                "health": self.derivative_health,
            },
            "basis_bps": float(self.basis_bps),
            "captured_at": self.captured_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class StrategyParameters:
    notional_jpy: Decimal = Decimal("100000")
    hold_hours: Decimal = Decimal("72")
    spot_taker_fee_bps: Decimal = Decimal("15")
    derivative_taker_fee_bps: Decimal = Decimal("0")
    slippage_bps_per_fill: Decimal = Decimal("2")
    leverage_point_daily_bps: Decimal = Decimal("4")
    basis_exit_buffer_bps: Decimal = Decimal("5")
    risk_buffer_bps: Decimal = Decimal("3")
    min_expected_net_bps: Decimal = Decimal("5")
    max_abs_basis_bps: Decimal = Decimal("100")
    max_data_age_seconds: Decimal = Decimal("30")
    max_order_btc: Decimal = Decimal("0.05")
    min_margin_keep_rate: Decimal = Decimal("1.8")
    max_daily_loss_jpy: Decimal = Decimal("10000")
    allow_negative_rate_inventory_hedge: bool = False

    def validate(self) -> None:
        non_negative = (
            "notional_jpy",
            "hold_hours",
            "spot_taker_fee_bps",
            "derivative_taker_fee_bps",
            "slippage_bps_per_fill",
            "leverage_point_daily_bps",
            "basis_exit_buffer_bps",
            "risk_buffer_bps",
            "min_expected_net_bps",
            "max_abs_basis_bps",
            "max_data_age_seconds",
            "max_order_btc",
            "min_margin_keep_rate",
            "max_daily_loss_jpy",
        )
        for name in non_negative:
            if decimal_value(getattr(self, name)) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.notional_jpy < Decimal("1000"):
            raise ValueError("notional_jpy must be at least 1,000 JPY")
        if self.hold_hours <= 0:
            raise ValueError("hold_hours must be greater than zero")
        if self.max_order_btc <= 0:
            raise ValueError("max_order_btc must be greater than zero")

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            payload[item.name] = value if isinstance(value, bool) else float(value)
        return payload

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> StrategyParameters:
        names = {item.name for item in fields(cls)}
        converted: dict[str, Any] = {}
        for name, value in values.items():
            if name not in names:
                continue
            if name == "allow_negative_rate_inventory_hedge":
                converted[name] = bool(value)
            else:
                converted[name] = decimal_value(value)
        result = cls(**converted)
        result.validate()
        return result


@dataclass(frozen=True, slots=True)
class EconomicsResult:
    accepted: bool
    action: str
    derivative_side: Side | None
    spot_side: Side | None
    intervals: int
    position_size_btc: Decimal
    funding_income_bps: Decimal
    leverage_cost_bps: Decimal
    trading_cost_bps: Decimal
    slippage_cost_bps: Decimal
    basis_cost_bps: Decimal
    risk_buffer_bps: Decimal
    net_bps: Decimal
    break_even_rate_bps_per_interval: Decimal
    expected_pnl_jpy: Decimal
    annualized_return_pct: Decimal
    executable_basis_bps: Decimal
    rejection_reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "action": self.action,
            "derivative_side": self.derivative_side.value if self.derivative_side else None,
            "spot_side": self.spot_side.value if self.spot_side else None,
            "intervals": self.intervals,
            "position_size_btc": float(self.position_size_btc),
            "funding_income_bps": float(self.funding_income_bps),
            "leverage_cost_bps": float(self.leverage_cost_bps),
            "trading_cost_bps": float(self.trading_cost_bps),
            "slippage_cost_bps": float(self.slippage_cost_bps),
            "basis_cost_bps": float(self.basis_cost_bps),
            "risk_buffer_bps": float(self.risk_buffer_bps),
            "net_bps": float(self.net_bps),
            "break_even_rate_bps_per_interval": float(
                self.break_even_rate_bps_per_interval
            ),
            "expected_pnl_jpy": float(self.expected_pnl_jpy),
            "annualized_return_pct": float(self.annualized_return_pct),
            "executable_basis_bps": float(self.executable_basis_bps),
            "rejection_reasons": list(self.rejection_reasons),
        }


@dataclass(frozen=True, slots=True)
class OrderIntent:
    venue: str
    product_code: str
    side: Side
    size: Decimal
    limit_price: Decimal
    unwind_price: Decimal
    leg: str

    def reversed_for_unwind(self) -> OrderIntent:
        return OrderIntent(
            venue=self.venue,
            product_code=self.product_code,
            side=self.side.opposite,
            size=self.size,
            limit_price=self.unwind_price,
            unwind_price=self.limit_price,
            leg=f"unwind:{self.leg}",
        )


@dataclass(frozen=True, slots=True)
class OrderReceipt:
    acceptance_id: str
    intent: OrderIntent


@dataclass(frozen=True, slots=True)
class OrderFill:
    state: OrderState
    filled_size: Decimal
    average_price: Decimal
    acceptance_id: str

    @property
    def fully_filled(self) -> bool:
        return self.state is OrderState.COMPLETED and self.filled_size > 0
