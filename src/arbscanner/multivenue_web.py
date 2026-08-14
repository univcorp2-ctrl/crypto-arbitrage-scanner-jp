from __future__ import annotations

import hmac
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, SecretStr

from .funding.multivenue import (
    CcxtVenueAdapter,
    FundingOpportunity,
    MultiVenueFundingEngine,
    MultiVenueSettings,
    VENUES,
    credential_statuses,
    live_readiness,
    policy_payload,
)
from .funding.vault import CredentialVault, VaultUnavailable

STATIC_DIR = Path(__file__).resolve().parent / "multivenue_static"


class SettingsInput(BaseModel):
    notional_usdt: float = Field(gt=0, le=10_000_000)
    holding_intervals: int = Field(ge=1, le=365)
    min_net_spread_bps: float = Field(ge=0, le=10_000)
    taker_fee_bps_each_leg: float = Field(ge=0, le=500)
    slippage_bps_each_leg: float = Field(ge=0, le=500)
    max_abs_basis_bps: float = Field(ge=0, le=10_000)
    depth_multiplier: float = Field(ge=1, le=100)
    max_live_notional_usdt: float = Field(gt=0, le=10_000_000)


class CredentialInput(BaseModel):
    api_key: SecretStr = Field(min_length=4, max_length=512)
    api_secret: SecretStr = Field(min_length=4, max_length=1024)


class KillInput(BaseModel):
    enabled: bool


class ExecuteInput(BaseModel):
    strategy: str = "perp_perp"
    asset: str = "BTC"
    long_venue: str
    short_venue: str
    long_symbol: str = "BTC/USDT:USDT"
    short_symbol: str = "BTC/USDT:USDT"
    long_rate: float
    short_rate: float
    spread_rate: float
    estimated_net_bps: float
    estimated_net_usdt: float
    eligible: bool
    blockers: list[str] = []


def _admin(request: Request, supplied: str | None) -> None:
    expected = os.getenv("FUNDING_ADMIN_TOKEN", "").strip()
    if expected:
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail="invalid admin token")
        return
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="write operations require FUNDING_ADMIN_TOKEN outside loopback")


class SettingsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> MultiVenueSettings:
        try:
            return MultiVenueSettings.from_mapping(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError):
            return MultiVenueSettings()

    def save(self, settings: MultiVenueSettings) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(settings.to_dict(), indent=2) + "\n", encoding="utf-8")
        temp.replace(self.path)


def create_app(*, settings_path: str | None = None, vault_path: str | None = None) -> FastAPI:
    store = SettingsStore(settings_path or os.getenv("FUNDING_MULTI_SETTINGS_PATH", "data/funding_multi_settings.json"))
    engine = MultiVenueFundingEngine(store.load())
    vault: CredentialVault | None = None
    vault_error: str | None = None
    vault_key = os.getenv("FUNDING_VAULT_KEY", "").strip()
    if vault_key and vault_key != "GENERATE_LOCALLY_DO_NOT_COMMIT":
        try:
            vault = CredentialVault(vault_path or os.getenv("FUNDING_VAULT_PATH", "data/funding_vault.db"), vault_key)
        except VaultUnavailable as exc:
            vault_error = str(exc)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = engine
        app.state.store = store
        app.state.vault = vault
        app.state.vault_error = vault_error
        yield

    app = FastAPI(title="Multi-Venue Funding Arbitrage JP", version="0.4.0", lifespan=lifespan)
    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="multi-assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz")
    async def health() -> dict[str, Any]:
        return {"ok": True, "kill_switch": engine.kill_switch, "automatic_withdrawals": False, "live_global": os.getenv("FUNDING_MULTI_LIVE_ENABLED", "false")}

    @app.get("/api/venues")
    async def venues() -> dict[str, Any]:
        return policy_payload()

    @app.get("/api/settings")
    async def settings() -> dict[str, Any]:
        return {"settings": engine.settings.to_dict()}

    @app.put("/api/settings")
    async def save_settings(payload: SettingsInput, request: Request, x_funding_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
        _admin(request, x_funding_admin_token)
        selected = MultiVenueSettings.from_mapping(payload.model_dump())
        store.save(selected)
        engine.settings = selected
        return {"saved": True, "settings": selected.to_dict()}

    @app.get("/api/credentials/status")
    async def creds_status() -> dict[str, Any]:
        return {"vault_available": vault is not None, "vault_error": vault_error, "venues": credential_statuses(vault)}

    @app.post("/api/credentials/{venue}")
    async def save_credentials(venue: str, payload: CredentialInput, request: Request, x_funding_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
        _admin(request, x_funding_admin_token)
        policy = VENUES.get(venue)
        if policy is None or not policy.ccxt_id or not policy.private_trading:
            raise HTTPException(status_code=422, detail="venue does not support this private connector")
        if vault is None:
            raise HTTPException(status_code=503, detail="credential vault unavailable")
        creds = {"api_key": payload.api_key.get_secret_value(), "api_secret": payload.api_secret.get_secret_value()}
        adapter = CcxtVenueAdapter.create(venue, creds)
        try:
            await adapter.exchange.load_markets()
            await adapter.exchange.fetch_balance()
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"credential verification failed: {type(exc).__name__}") from exc
        finally:
            await adapter.close()
        status = vault.save(venue, creds["api_key"], creds["api_secret"])
        return {"saved": True, "status": status.to_dict(), "secret_values_returned": False}

    @app.post("/api/credentials/{venue}/disable")
    async def disable_credentials(venue: str, request: Request, x_funding_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
        _admin(request, x_funding_admin_token)
        if vault is None:
            raise HTTPException(status_code=503, detail="credential vault unavailable")
        return {"status": vault.disable(venue).to_dict()}

    @app.get("/api/readiness/{venue}")
    async def readiness(venue: str) -> dict[str, Any]:
        return live_readiness(venue, engine.settings, vault)

    @app.post("/api/scan")
    async def scan(venues: str = "mexc,gate,bitrue,bitget,okx,bingx", symbol: str = "BTC/USDT:USDT") -> dict[str, Any]:
        selected = [v.strip().lower() for v in venues.split(",") if v.strip()]
        return await engine.scan_perpetuals(selected, symbol)

    @app.post("/api/kill-switch")
    async def kill(payload: KillInput, request: Request, x_funding_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
        _admin(request, x_funding_admin_token)
        engine.kill_switch = payload.enabled
        return {"kill_switch": engine.kill_switch}

    @app.post("/api/execute")
    async def execute(payload: ExecuteInput, request: Request, x_funding_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
        _admin(request, x_funding_admin_token)
        if vault is None:
            raise HTTPException(status_code=503, detail="credential vault unavailable")
        opportunity = FundingOpportunity(
            payload.strategy, payload.asset, payload.long_venue, payload.short_venue,
            payload.long_symbol, payload.short_symbol, payload.long_rate, payload.short_rate,
            payload.spread_rate, payload.estimated_net_bps, payload.estimated_net_usdt,
            payload.eligible, tuple(payload.blockers),
        )
        return await engine.execute_perp_spread(opportunity, vault)

    return app


def main() -> None:
    uvicorn.run(create_app(), host=os.getenv("FUNDING_MULTI_HOST", "127.0.0.1"), port=int(os.getenv("FUNDING_MULTI_PORT", "8011")))


if __name__ == "__main__":
    main()
