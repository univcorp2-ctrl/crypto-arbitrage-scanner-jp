from __future__ import annotations

import argparse
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .exchange_catalog import catalog_payload
from .simulation import SimulationEngine, SimulationStore

STATIC_DIR = Path(__file__).resolve().parent / "static"


class RiskUpdate(BaseModel):
    min_net_bps: float | None = Field(default=None, ge=0.0, le=1000.0)
    max_notional_jpy: float | None = Field(default=None, ge=1_000.0, le=100_000_000.0)
    max_daily_loss_jpy: float | None = Field(default=None, ge=1_000.0, le=100_000_000.0)
    max_slippage_bps: float | None = Field(default=None, ge=0.0, le=100.0)
    min_jpy_reserve: float | None = Field(default=None, ge=0.0, le=100_000_000.0)
    min_btc_reserve: float | None = Field(default=None, ge=0.0, le=100.0)


class ModeUpdate(BaseModel):
    mode: str


class KillSwitchUpdate(BaseModel):
    enabled: bool


class ResetRequest(BaseModel):
    seed: int | None = None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def create_app(
    *,
    db_path: str | None = None,
    config_path: str | None = None,
    autostart: bool | None = None,
) -> FastAPI:
    selected_db_path = db_path or os.getenv("ARB_DB_PATH", "data/arbscanner.db")
    selected_config_path = config_path or os.getenv("ARB_CONFIG_PATH", "config.yml")
    selected_interval = float(os.getenv("ARB_SIM_INTERVAL_SECONDS", "30"))
    selected_mode = os.getenv("ARB_MODE", "public-live-paper")
    selected_autostart = _env_bool("ARB_AUTOSTART", True) if autostart is None else autostart

    @asynccontextmanager
    async def lifespan(current_app: FastAPI) -> AsyncIterator[None]:
        store = SimulationStore(selected_db_path)
        engine = SimulationEngine(
            store,
            config_path=selected_config_path,
            interval_seconds=selected_interval,
            mode=selected_mode,
        )
        engine.initialize()
        current_app.state.engine = engine
        if selected_autostart:
            await engine.start()
        try:
            yield
        finally:
            await engine.close()

    application = FastAPI(
        title="Crypto Arbitrage Operations Console",
        version="0.2.0",
        description="Public-market paper trading only. Real order submission is disabled.",
        lifespan=lifespan,
    )
    application.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/healthz")
    async def healthz(request: Request) -> dict[str, Any]:
        engine = _engine(request)
        return {
            "ok": True,
            "mode": engine.mode,
            "running": engine.running,
            "real_order_submission": False,
        }

    @application.get("/api/overview")
    async def overview(request: Request) -> dict[str, Any]:
        return _engine(request).overview()

    @application.get("/api/exchanges")
    async def exchanges() -> dict[str, Any]:
        return {
            "items": catalog_payload(),
            "secret_values_returned": False,
            "research_as_of": "2026-08-07",
        }

    @application.post("/api/simulation/start")
    async def start(request: Request) -> dict[str, Any]:
        engine = _engine(request)
        await engine.start()
        return engine.status()

    @application.post("/api/simulation/stop")
    async def stop(request: Request) -> dict[str, Any]:
        engine = _engine(request)
        await engine.stop()
        return engine.status()

    @application.post("/api/simulation/tick")
    async def tick(request: Request) -> dict[str, Any]:
        return await _engine(request).run_once()

    @application.post("/api/simulation/reset")
    async def reset(payload: ResetRequest, request: Request) -> dict[str, Any]:
        engine = _engine(request)
        engine.reset(seed=payload.seed)
        return engine.overview()

    @application.put("/api/risk")
    async def update_risk(payload: RiskUpdate, request: Request) -> dict[str, Any]:
        updates = payload.model_dump(exclude_none=True)
        risk = _engine(request).set_risk(**updates)
        return {"risk": risk.__dict__}

    @application.put("/api/mode")
    async def update_mode(payload: ModeUpdate, request: Request) -> dict[str, Any]:
        try:
            mode = _engine(request).set_mode(payload.mode)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"mode": mode}

    @application.put("/api/kill-switch")
    async def update_kill_switch(
        payload: KillSwitchUpdate, request: Request
    ) -> dict[str, Any]:
        enabled = _engine(request).set_kill_switch(payload.enabled)
        return {"kill_switch": enabled}

    return application


def _engine(request: Request) -> SimulationEngine:
    engine = getattr(request.app.state, "engine", None)
    if not isinstance(engine, SimulationEngine):
        raise HTTPException(status_code=503, detail="simulation engine is not ready")
    return engine


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the paper-trading web dashboard.")
    parser.add_argument("--host", default=os.getenv("ARB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("ARB_PORT", "8000")))
    parser.add_argument("--db", default=os.getenv("ARB_DB_PATH", "data/arbscanner.db"))
    parser.add_argument("--config", default=os.getenv("ARB_CONFIG_PATH", "config.yml"))
    parser.add_argument("--no-autostart", action="store_true")
    args = parser.parse_args()
    application = create_app(
        db_path=args.db,
        config_path=args.config,
        autostart=not args.no_autostart,
    )
    uvicorn.run(application, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
