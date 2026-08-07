from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from .models import OrderFill, OrderIntent, OrderReceipt


class ExecutionStatus(StrEnum):
    COMPLETED = "completed"
    ABORTED_FIRST_LEG = "aborted_first_leg"
    RECOVERED_SECOND_LEG_FAILURE = "recovered_second_leg_failure"
    EMERGENCY_UNHEDGED = "emergency_unhedged"


class ExecutionAdapter(Protocol):
    async def submit(self, intent: OrderIntent) -> OrderReceipt: ...

    async def wait(self, receipt: OrderReceipt) -> OrderFill: ...

    async def cancel(self, receipt: OrderReceipt) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    status: ExecutionStatus
    first_fill: OrderFill | None
    second_fill: OrderFill | None
    recovery_fill: OrderFill | None
    message: str

    @property
    def hedged(self) -> bool:
        return self.status in {
            ExecutionStatus.COMPLETED,
            ExecutionStatus.RECOVERED_SECOND_LEG_FAILURE,
        }


class TwoLegExecutor:
    """Bounded two-leg coordinator intended for FOK limit orders.

    A failed second leg triggers a compensating reverse order for the first leg. The caller must
    trigger the independent kill switch when EMERGENCY_UNHEDGED is returned.
    """

    def __init__(self, adapter: ExecutionAdapter) -> None:
        self.adapter = adapter

    async def execute(
        self,
        first: OrderIntent,
        second: OrderIntent,
    ) -> ExecutionOutcome:
        self._validate_pair(first, second)
        first_receipt = await self.adapter.submit(first)
        first_fill = await self.adapter.wait(first_receipt)
        if not self._is_full(first_fill, first.size):
            await self.adapter.cancel(first_receipt)
            return ExecutionOutcome(
                status=ExecutionStatus.ABORTED_FIRST_LEG,
                first_fill=first_fill,
                second_fill=None,
                recovery_fill=None,
                message="first leg did not fill completely; pair was not opened",
            )

        second_receipt = await self.adapter.submit(second)
        second_fill = await self.adapter.wait(second_receipt)
        if self._is_full(second_fill, second.size):
            return ExecutionOutcome(
                status=ExecutionStatus.COMPLETED,
                first_fill=first_fill,
                second_fill=second_fill,
                recovery_fill=None,
                message="both legs completed",
            )

        await self.adapter.cancel(second_receipt)
        recovery_receipt = await self.adapter.submit(first.reversed_for_unwind())
        recovery_fill = await self.adapter.wait(recovery_receipt)
        if self._is_full(recovery_fill, first.size):
            return ExecutionOutcome(
                status=ExecutionStatus.RECOVERED_SECOND_LEG_FAILURE,
                first_fill=first_fill,
                second_fill=second_fill,
                recovery_fill=recovery_fill,
                message="second leg failed; first leg was unwound",
            )
        return ExecutionOutcome(
            status=ExecutionStatus.EMERGENCY_UNHEDGED,
            first_fill=first_fill,
            second_fill=second_fill,
            recovery_fill=recovery_fill,
            message="recovery order failed; enable kill switch and reconcile immediately",
        )

    @staticmethod
    def _validate_pair(first: OrderIntent, second: OrderIntent) -> None:
        if first.venue != second.venue:
            raise ValueError("this coordinator requires both legs on the same venue")
        if first.side is second.side:
            raise ValueError("delta-neutral legs must use opposite sides")
        if first.size <= 0 or second.size <= 0:
            raise ValueError("order sizes must be positive")
        if abs(first.size - second.size) > Decimal("0.00000001"):
            raise ValueError("order sizes must match")

    @staticmethod
    def _is_full(fill: OrderFill, expected_size: Decimal) -> bool:
        return fill.fully_filled and fill.filled_size >= expected_size
