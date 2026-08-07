from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import httpx

from .models import (
    FundingRatePoint,
    FundingSnapshot,
    OrderFill,
    OrderIntent,
    OrderReceipt,
    OrderState,
    decimal_value,
)

BASE_URL = "https://api.bitflyer.com"
READ_PERMISSIONS = {
    "/v1/me/getpermissions",
    "/v1/me/getbalance",
    "/v1/me/getcollateral",
    "/v1/me/getpositions",
    "/v1/me/getchildorders",
    "/v1/me/getexecutions",
}
TRADE_PERMISSIONS = {
    "/v1/me/sendchildorder",
    "/v1/me/cancelchildorder",
}
FORBIDDEN_PERMISSION_MARKERS = ("withdraw", "sendcoin", "transfer", "sendcollateral")


class BitflyerApiError(RuntimeError):
    pass


class LiveTradingDisabled(RuntimeError):
    pass


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def _response_json(response: httpx.Response) -> Any:
    try:
        payload = response.json()
    except ValueError as exc:
        raise BitflyerApiError("bitFlyer returned non-JSON data") from exc
    if response.is_error:
        raise BitflyerApiError(f"bitFlyer HTTP error: {response.status_code}")
    if isinstance(payload, dict) and int(payload.get("status", 0)) < 0:
        raise BitflyerApiError(str(payload.get("error_message", "bitFlyer API error")))
    return payload


class BitflyerPublicClient:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            headers={"User-Agent": "arb-control-funding/0.3"},
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        try:
            response = await self._client.get(f"{BASE_URL}{path}", params=params)
        except httpx.HTTPError as exc:
            raise BitflyerApiError("bitFlyer public API request failed") from exc
        return await _response_json(response)

    async def snapshot(self) -> FundingSnapshot:
        spot_task = self._get("/v1/getticker", {"product_code": "BTC_JPY"})
        derivative_task = self._get("/v1/getticker", {"product_code": "FX_BTC_JPY"})
        funding_task = self._get("/v1/getfundingrate", {"product_code": "FX_BTC_JPY"})
        spot_health_task = self._get("/v1/gethealth", {"product_code": "BTC_JPY"})
        derivative_health_task = self._get(
            "/v1/gethealth", {"product_code": "FX_BTC_JPY"}
        )
        spot, derivative, funding, spot_health, derivative_health = await asyncio.gather(
            spot_task,
            derivative_task,
            funding_task,
            spot_health_task,
            derivative_health_task,
        )
        return FundingSnapshot(
            venue="bitflyer",
            symbol="BTC/JPY",
            funding_rate=decimal_value(funding["current_funding_rate"]),
            funding_interval_hours=Decimal("8"),
            next_settlement=_parse_datetime(funding["next_funding_rate_settledate"]),
            spot_bid=decimal_value(spot["best_bid"]),
            spot_ask=decimal_value(spot["best_ask"]),
            derivative_bid=decimal_value(derivative["best_bid"]),
            derivative_ask=decimal_value(derivative["best_ask"]),
            captured_at=datetime.now(timezone.utc),
            spot_health=str(spot_health.get("status", "UNKNOWN")),
            derivative_health=str(derivative_health.get("status", "UNKNOWN")),
        )

    async def funding_history(self, count: int = 30) -> tuple[FundingRatePoint, ...]:
        safe_count = min(max(count, 1), 500)
        payload = await self._get(
            "/v1/getfundingratehistory",
            {"product_code": "FX_BTC_JPY", "count": safe_count},
        )
        return tuple(
            FundingRatePoint(
                rate=decimal_value(item["rate"]),
                calculation_date=_parse_datetime(item["calculation_date"]),
                settlement_date=_parse_datetime(item["settlement_date"]),
            )
            for item in payload
        )


@dataclass(frozen=True, slots=True)
class PermissionReport:
    safe: bool
    read_ready: bool
    trade_ready: bool
    missing_read_permissions: tuple[str, ...]
    missing_trade_permissions: tuple[str, ...]
    forbidden_permissions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "safe": self.safe,
            "read_ready": self.read_ready,
            "trade_ready": self.trade_ready,
            "missing_read_permissions": list(self.missing_read_permissions),
            "missing_trade_permissions": list(self.missing_trade_permissions),
            "forbidden_permissions": list(self.forbidden_permissions),
        }


def inspect_permissions(permissions: list[str]) -> PermissionReport:
    normalized = {str(item).strip() for item in permissions}
    missing_read = tuple(sorted(READ_PERMISSIONS - normalized))
    missing_trade = tuple(sorted(TRADE_PERMISSIONS - normalized))
    forbidden = tuple(
        sorted(
            permission
            for permission in normalized
            if any(marker in permission.lower() for marker in FORBIDDEN_PERMISSION_MARKERS)
        )
    )
    return PermissionReport(
        safe=not forbidden,
        read_ready=not missing_read,
        trade_ready=not missing_trade,
        missing_read_permissions=missing_read,
        missing_trade_permissions=missing_trade,
        forbidden_permissions=forbidden,
    )


@dataclass(frozen=True, slots=True)
class LiveGate:
    enabled: bool
    max_order_btc: Decimal

    @classmethod
    def from_environment(cls) -> LiveGate:
        explicit_enabled = os.getenv("FUNDING_LIVE_ENABLED", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        execution_mode = os.getenv("FUNDING_EXECUTION_MODE", "paper").lower()
        return cls(
            enabled=explicit_enabled and execution_mode == "live",
            max_order_btc=decimal_value(os.getenv("FUNDING_MAX_ORDER_BTC", "0.05")),
        )

    def check(self, intent: OrderIntent) -> None:
        if not self.enabled:
            raise LiveTradingDisabled("live trading is locked by environment configuration")
        if intent.product_code not in {"BTC_JPY", "FX_BTC_JPY"}:
            raise LiveTradingDisabled("product is outside the live allowlist")
        if intent.size < Decimal("0.001") or intent.size > self.max_order_btc:
            raise LiveTradingDisabled("order size is outside the live safety envelope")
        if intent.limit_price <= 0:
            raise LiveTradingDisabled("limit price must be positive")


class BitflyerPrivateClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        client: httpx.AsyncClient | None = None,
        gate: LiveGate | None = None,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("bitFlyer API key and secret are required")
        self._api_key = api_key
        self._api_secret = api_secret.encode()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self._gate = gate or LiveGate.from_environment()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        query = urlencode([(key, str(value)) for key, value in (params or {}).items()])
        signed_path = f"{path}?{query}" if query else path
        body_text = (
            json.dumps(body, ensure_ascii=False, separators=(",", ":")) if body else ""
        )
        timestamp = str(time.time())
        message = f"{timestamp}{method.upper()}{signed_path}{body_text}".encode()
        signature = hmac.new(self._api_secret, message, hashlib.sha256).hexdigest()
        headers = {
            "ACCESS-KEY": self._api_key,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-SIGN": signature,
            "Content-Type": "application/json",
        }
        try:
            response = await self._client.request(
                method.upper(),
                f"{BASE_URL}{signed_path}",
                content=body_text or None,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise BitflyerApiError("bitFlyer private API request failed") from exc
        return await _response_json(response)

    async def get_permissions(self) -> list[str]:
        payload = await self._request("GET", "/v1/me/getpermissions")
        return [str(item) for item in payload]

    async def get_balances(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/v1/me/getbalance")
        return list(payload)

    async def get_collateral(self) -> dict[str, Any]:
        payload = await self._request("GET", "/v1/me/getcollateral")
        return dict(payload)

    async def get_positions(self) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET", "/v1/me/getpositions", params={"product_code": "FX_BTC_JPY"}
        )
        return list(payload)

    async def submit_limit_fok(self, intent: OrderIntent) -> OrderReceipt:
        self._gate.check(intent)
        payload = await self._request(
            "POST",
            "/v1/me/sendchildorder",
            body={
                "product_code": intent.product_code,
                "child_order_type": "LIMIT",
                "side": intent.side.value,
                "price": int(intent.limit_price),
                "size": float(intent.size),
                "minute_to_expire": 1,
                "time_in_force": "FOK",
            },
        )
        return OrderReceipt(str(payload["child_order_acceptance_id"]), intent)

    async def cancel(self, receipt: OrderReceipt) -> None:
        await self._request(
            "POST",
            "/v1/me/cancelchildorder",
            body={
                "product_code": receipt.intent.product_code,
                "child_order_acceptance_id": receipt.acceptance_id,
            },
        )

    async def get_fill(self, receipt: OrderReceipt) -> OrderFill | None:
        payload = await self._request(
            "GET",
            "/v1/me/getchildorders",
            params={
                "product_code": receipt.intent.product_code,
                "child_order_acceptance_id": receipt.acceptance_id,
            },
        )
        if not payload:
            return None
        item = payload[0]
        raw_state = str(item.get("child_order_state", "UNKNOWN"))
        state = OrderState(raw_state) if raw_state in OrderState._value2member_map_ else OrderState.UNKNOWN
        return OrderFill(
            state=state,
            filled_size=decimal_value(item.get("executed_size", 0)),
            average_price=decimal_value(item.get("average_price", 0)),
            acceptance_id=receipt.acceptance_id,
        )

    async def wait_for_fill(
        self, receipt: OrderReceipt, *, timeout_seconds: float = 4.0
    ) -> OrderFill:
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            fill = await self.get_fill(receipt)
            if fill and fill.state not in {OrderState.ACTIVE, OrderState.PENDING}:
                return fill
            await asyncio.sleep(0.25)
        return OrderFill(
            state=OrderState.UNKNOWN,
            filled_size=Decimal("0"),
            average_price=Decimal("0"),
            acceptance_id=receipt.acceptance_id,
        )
