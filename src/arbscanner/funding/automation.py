from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from .bitflyer import BitflyerApiError, BitflyerPublicClient
from .economics import evaluate_opportunity
from .models import EconomicsResult, FundingSnapshot, StrategyParameters


@dataclass(frozen=True, slots=True)
class PaperFundingPosition:
    size_btc: Decimal
    opened_at: datetime
    planned_exit_at: datetime
    entry_spot_price: Decimal
    entry_derivative_price: Decimal
    expected_net_bps: Decimal

    def to_dict(self) -> dict[str, Any]:
        return {
            "size_btc": float(self.size_btc),
            "opened_at": self.opened_at.isoformat(),
            "planned_exit_at": self.planned_exit_at.isoformat(),
            "entry_spot_price": float(self.entry_spot_price),
            "entry_derivative_price": float(self.entry_derivative_price),
            "expected_net_bps": float(self.expected_net_bps),
        }


class FundingAutomationService:
    """Automatic scanner and paper/shadow position lifecycle.

    Live order primitives are deliberately separate. This service never submits real orders or
    transfers funds; that keeps the public and default local deployment safe.
    """

    def __init__(
        self,
        public_client: BitflyerPublicClient,
        parameters: StrategyParameters,
        *,
        interval_seconds: float = 15.0,
        mode: str = "paper",
    ) -> None:
        if mode not in {"paper", "shadow"}:
            raise ValueError("automation service supports paper or shadow mode")
        self.public_client = public_client
        self.parameters = parameters
        self.interval_seconds = max(5.0, interval_seconds)
        self.mode = mode
        self.running = False
        self.position: PaperFundingPosition | None = None
        self.last_snapshot: FundingSnapshot | None = None
        self.last_result: EconomicsResult | None = None
        self.last_error: str | None = None
        self.events: list[dict[str, Any]] = []
        self._task: asyncio.Task[None] | None = None

    def set_parameters(self, parameters: StrategyParameters) -> None:
        parameters.validate()
        self.parameters = parameters

    async def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="funding-paper-loop")
        self._event("info", "automation_started")

    async def stop(self) -> None:
        self.running = False
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._event("info", "automation_stopped")

    async def close(self) -> None:
        await self.stop()

    async def _loop(self) -> None:
        while self.running:
            try:
                await self.tick()
            except BitflyerApiError as exc:
                self.last_error = str(exc)
                self._event("error", "market_fetch_failed")
            except Exception as exc:  # noqa: BLE001 - loop must stop safely, not crash silently.
                self.last_error = type(exc).__name__
                self._event("error", "automation_cycle_failed")
            await asyncio.sleep(self.interval_seconds)

    async def tick(self) -> dict[str, Any]:
        snapshot = await self.public_client.snapshot()
        result = evaluate_opportunity(snapshot, self.parameters)
        self.last_snapshot = snapshot
        self.last_result = result
        self.last_error = None
        now = datetime.now(timezone.utc)

        event = "no_trade"
        if self.position is None and result.accepted:
            event = "paper_position_opened" if self.mode == "paper" else "shadow_signal_created"
            self.position = PaperFundingPosition(
                size_btc=result.position_size_btc,
                opened_at=now,
                planned_exit_at=now + timedelta(hours=float(self.parameters.hold_hours)),
                entry_spot_price=snapshot.spot_ask,
                entry_derivative_price=snapshot.derivative_bid,
                expected_net_bps=result.net_bps,
            )
            self._event("info", event)
        elif self.position is not None:
            should_close = now >= self.position.planned_exit_at or snapshot.funding_rate <= 0
            if should_close:
                event = "paper_position_closed" if self.mode == "paper" else "shadow_signal_closed"
                self.position = None
                self._event("info", event)
        return {
            "event": event,
            "snapshot": snapshot.to_dict(),
            "evaluation": result.to_dict(),
            "status": self.status(),
        }

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "mode": self.mode,
            "real_order_submission": False,
            "automatic_transfers": False,
            "position": self.position.to_dict() if self.position else None,
            "last_error": self.last_error,
            "last_snapshot": self.last_snapshot.to_dict() if self.last_snapshot else None,
            "last_evaluation": self.last_result.to_dict() if self.last_result else None,
            "events": self.events[-50:],
        }

    def _event(self, level: str, event: str) -> None:
        self.events.append(
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "event": event,
            }
        )
        self.events = self.events[-200:]
