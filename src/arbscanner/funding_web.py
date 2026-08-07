from __future__ import annotations

import argparse
import asyncio
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

from .funding.automation import FundingAutomationService
from .funding.bitflyer import (
    BitflyerApiError,
    BitflyerPrivateClient,
    BitflyerPublicClient,
    inspect_permissions,
)
from .funding.economics import evaluate_opportunity
from .funding.models import StrategyParameters
from .funding.policy import policy_payload
from .funding.vault import CredentialVault, VaultUnavailable

STATIC_DIR = Path(__file__).resolve().parent / "funding_static"


class ParameterUpdate(BaseModel):
    notional_jpy: float = Field(ge=1_000, le=100_000_000)
    hold_hours: float = Field(gt=0, le=24 * 365)
    spot_taker_fee_bps: float = Field(ge=0, le=500)
    derivative_taker_fee_bps: float = Field(ge=0, le=500)
    slippage_bps_per_fill: float = Field(ge=0, le=500)
    leverage_point_daily_bps: float = Field(ge=0, le=500)
    basis_exit_buffer_bps: float = Field(ge=0, le=2_000)
    risk_buffer_bps: float = Field(ge=0, le=2_000)
    min_expected_net_bps: float = Field(ge=0, le=2_000)
    max_abs_basis_bps: float = Field(ge=0, le=5_000)
    max_data_age_seconds: float = Field(ge=1, le=3_600)
    max_order_btc: float = Field(gt=0, le=10)
    min_margin_keep_rate: float = Field(ge=1, le=20)
    max_daily_loss_jpy: float = Field(ge=1_000, le=100_000_000)
    allow_negative_rate_inventory_hedge: bool = False


class CredentialInput(BaseModel):
    api_key: SecretStr = Field(min_length=8, max_length=256)
    api_secret: SecretStr = Field(min_length=8, max_length=512)


class SettingsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> StrategyParameters:
        if not self.path.exists():
            return StrategyParameters()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return StrategyParameters.from_mapping(payload)
        except (OSError, ValueError, json.JSONDecodeError):
            return StrategyParameters()

    def save(self, parameters: StrategyParameters) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(parameters.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _require_admin(request: Request, supplied_token: str | None) -> None:
    expected = os.getenv("FUNDING_ADMIN_TOKEN", "").strip()
    if expected:
        if not supplied_token or not hmac.compare_digest(supplied_token, expected):
            raise HTTPException(status_code=401, detail="invalid admin token")
        return
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(
            status_code=403,
            detail="write operations require FUNDING_ADMIN_TOKEN outside loopback",
        )


def create_app(
    *,
    settings_path: str | None = None,
    vault_path: str | None = None,
    autostart: bool | None = None,
) -> FastAPI:
    selected_settings_path = settings_path or os.getenv(
        "FUNDING_SETTINGS_PATH", "data/funding_settings.json"
    )
    selected_vault_path = vault_path or os.getenv(
        "FUNDING_VAULT_PATH", "data/funding_vault.db"
    )
    selected_interval = float(os.getenv("FUNDING_SCAN_INTERVAL_SECONDS", "15"))
    selected_mode = os.getenv("FUNDING_MODE", "paper").lower()
    selected_autostart = (
        _env_bool("FUNDING_AUTOSTART", False) if autostart is None else autostart
    )
    settings_store = SettingsStore(selected_settings_path)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        public_client = BitflyerPublicClient()
        parameters = settings_store.load()
        service = FundingAutomationService(
            public_client,
            parameters,
            interval_seconds=selected_interval,
            mode=selected_mode,
        )
        vault: CredentialVault | None = None
        vault_error: str | None = None
        vault_key = os.getenv("FUNDING_VAULT_KEY", "").strip()
        if vault_key and vault_key != "GENERATE_LOCALLY_DO_NOT_COMMIT":
            try:
                vault = CredentialVault(selected_vault_path, vault_key)
            except VaultUnavailable as exc:
                vault_error = str(exc)
        application.state.public_client = public_client
        application.state.service = service
        application.state.settings_store = settings_store
        application.state.vault = vault
        application.state.vault_error = vault_error
        if selected_autostart:
            await service.start()
        try:
            yield
        finally:
            await service.close()
            await public_client.close()

    application = FastAPI(
        title="Funding Arbitrage Control JP",
        version="0.3.0",
        description="Japan-resident funding research and guarded paper automation.",
        lifespan=lifespan,
    )
    application.mount("/assets", StaticFiles(directory=STATIC_DIR), name="funding-assets")

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/healthz")
    async def healthz(request: Request) -> dict[str, Any]:
        service = _service(request)
        return {
            "ok": True,
            "mode": service.mode,
            "running": service.running,
            "real_order_submission": False,
            "automatic_withdrawals": False,
        }

    @application.get("/api/funding/market")
    async def market(request: Request) -> dict[str, Any]:
        public_client = _public_client(request)
        try:
            snapshot, history = await asyncio.gather(
                public_client.snapshot(), public_client.funding_history(30)
            )
        except BitflyerApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        evaluation = evaluate_opportunity(snapshot, _service(request).parameters)
        return {
            "ok": True,
            "source": "bitflyer_public_api",
            "market": snapshot.to_dict(),
            "funding_history": [point.to_dict() for point in history],
            "evaluation": evaluation.to_dict(),
            "real_order_submission": False,
        }

    @application.get("/api/funding/policy")
    async def policy() -> dict[str, Any]:
        return policy_payload()

    @application.get("/api/funding/settings")
    async def get_settings(request: Request) -> dict[str, Any]:
        return {"settings": _service(request).parameters.to_dict()}

    @application.put("/api/funding/settings")
    async def put_settings(
        payload: ParameterUpdate,
        request: Request,
        x_funding_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_admin(request, x_funding_admin_token)
        parameters = StrategyParameters.from_mapping(payload.model_dump())
        store = _settings_store(request)
        store.save(parameters)
        _service(request).set_parameters(parameters)
        return {"settings": parameters.to_dict(), "saved": True}

    @application.get("/api/funding/credentials/status")
    async def credential_status(request: Request) -> dict[str, Any]:
        vault = getattr(request.app.state, "vault", None)
        error = getattr(request.app.state, "vault_error", None)
        status = vault.status("bitflyer").to_dict() if vault else {
            "venue": "bitflyer",
            "configured": False,
            "active": False,
            "updated_at": None,
            "secret_values_returned": False,
        }
        return {
            "vault_available": vault is not None,
            "vault_error": error,
            "bitflyer": status,
            "live_environment_enabled": _env_bool("FUNDING_LIVE_ENABLED", False),
            "execution_mode": os.getenv("FUNDING_EXECUTION_MODE", "paper"),
        }

    @application.post("/api/funding/credentials/bitflyer")
    async def save_bitflyer_credentials(
        payload: CredentialInput,
        request: Request,
        x_funding_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_admin(request, x_funding_admin_token)
        vault = _vault(request)
        api_key = payload.api_key.get_secret_value()
        api_secret = payload.api_secret.get_secret_value()
        client = BitflyerPrivateClient(api_key, api_secret)
        try:
            permissions = await client.get_permissions()
        except BitflyerApiError as exc:
            raise HTTPException(status_code=422, detail="bitFlyer credential verification failed") from exc
        finally:
            await client.close()
        report = inspect_permissions(permissions)
        if not report.safe:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": "credential has forbidden withdrawal or transfer permission",
                    "permission_report": report.to_dict(),
                },
            )
        status = vault.save("bitflyer", api_key, api_secret)
        return {
            "saved": True,
            "bitflyer": status.to_dict(),
            "permission_report": report.to_dict(),
            "secret_values_returned": False,
        }

    @application.post("/api/funding/credentials/bitflyer/disable")
    async def disable_bitflyer_credentials(
        request: Request,
        x_funding_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_admin(request, x_funding_admin_token)
        return {"bitflyer": _vault(request).disable("bitflyer").to_dict()}

    @application.get("/api/funding/automation/status")
    async def automation_status(request: Request) -> dict[str, Any]:
        return _service(request).status()

    @application.post("/api/funding/automation/start")
    async def automation_start(
        request: Request,
        x_funding_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_admin(request, x_funding_admin_token)
        await _service(request).start()
        return _service(request).status()

    @application.post("/api/funding/automation/stop")
    async def automation_stop(
        request: Request,
        x_funding_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_admin(request, x_funding_admin_token)
        await _service(request).stop()
        return _service(request).status()

    @application.post("/api/funding/automation/tick")
    async def automation_tick(
        request: Request,
        x_funding_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_admin(request, x_funding_admin_token)
        try:
            return await _service(request).tick()
        except BitflyerApiError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    return application


def _service(request: Request) -> FundingAutomationService:
    service = getattr(request.app.state, "service", None)
    if not isinstance(service, FundingAutomationService):
        raise HTTPException(status_code=503, detail="funding service is not ready")
    return service


def _public_client(request: Request) -> BitflyerPublicClient:
    client = getattr(request.app.state, "public_client", None)
    if not isinstance(client, BitflyerPublicClient):
        raise HTTPException(status_code=503, detail="market client is not ready")
    return client


def _settings_store(request: Request) -> SettingsStore:
    store = getattr(request.app.state, "settings_store", None)
    if not isinstance(store, SettingsStore):
        raise HTTPException(status_code=503, detail="settings store is not ready")
    return store


def _vault(request: Request) -> CredentialVault:
    vault = getattr(request.app.state, "vault", None)
    if not isinstance(vault, CredentialVault):
        raise HTTPException(
            status_code=503,
            detail="encrypted vault is unavailable; configure FUNDING_VAULT_KEY",
        )
    return vault


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the funding arbitrage control plane.")
    parser.add_argument("--host", default=os.getenv("FUNDING_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("FUNDING_PORT", "8100")))
    parser.add_argument("--no-autostart", action="store_true")
    args = parser.parse_args()
    application = create_app(autostart=False if args.no_autostart else None)
    uvicorn.run(application, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
