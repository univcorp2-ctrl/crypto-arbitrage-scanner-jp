from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .paper import PaperSettings, PaperTradingService
from .storage import PaperStore


class SettingsRequest(BaseModel):
    min_net_bps: float = Field(ge=0, le=1000)
    max_trade_jpy: float = Field(gt=0, le=100_000_000)
    min_trade_jpy: float = Field(gt=0, le=100_000_000)
    slippage_bps: float = Field(ge=0, le=1000)
    rebalance_reserve_bps: float = Field(ge=0, le=1000)
    interval_seconds: int = Field(ge=5, le=86_400)


class SwitchRequest(BaseModel):
    enabled: bool


def create_app(
    db_path: str | Path | None = None,
    autostart: bool | None = None,
) -> FastAPI:
    resolved_db = db_path or os.getenv("ARB_DB_PATH", "data/arbscanner.db")
    settings = PaperSettings.from_env()
    if autostart is not None:
        settings.autostart = autostart
    service = PaperTradingService(PaperStore(resolved_db), settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if service.settings.autostart:
            await service.start()
        yield
        if service.running:
            await service.stop()

    app = FastAPI(
        title="JP Crypto Arbitrage Paper Console",
        version="0.2.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.state.service = service
    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "mode": "paper",
            "running": service.running,
            "kill_switch": service.kill_switch_enabled,
        }

    @app.get("/api/dashboard")
    async def dashboard() -> dict[str, object]:
        return service.dashboard_payload()

    @app.get("/api/trades")
    async def trades(limit: int = 200) -> dict[str, object]:
        return {"items": service.store.list_trades(limit)}

    @app.get("/api/performance")
    async def performance() -> dict[str, object]:
        payload = service.dashboard_payload()
        return {
            "performance": payload["performance"],
            "equity": payload["equity"],
        }

    @app.post("/api/paper/run-once")
    async def paper_run_once() -> dict[str, object]:
        return await service.run_once()

    @app.post("/api/paper/start")
    async def paper_start() -> dict[str, object]:
        return await service.start()

    @app.post("/api/paper/stop")
    async def paper_stop() -> dict[str, object]:
        return await service.stop()

    @app.put("/api/settings/paper")
    async def update_settings(body: SettingsRequest) -> dict[str, object]:
        return {"settings": service.update_settings(body.model_dump())}

    @app.post("/api/risk/kill-switch")
    async def kill_switch(body: SwitchRequest) -> dict[str, object]:
        return await service.set_kill_switch(body.enabled)

    return app


def main() -> None:
    host = os.getenv("ARB_HOST", "127.0.0.1")
    port = int(os.getenv("ARB_PORT", "8000"))
    uvicorn.run(create_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
