from __future__ import annotations

from fastapi.testclient import TestClient

from arbscanner.multivenue_web import create_app


def test_multivenue_console_and_policy(tmp_path) -> None:
    app = create_app(settings_path=str(tmp_path / "settings.json"), vault_path=str(tmp_path / "vault.db"))
    with TestClient(app) as client:
        page = client.get("/")
        venues = client.get("/api/venues")
        health = client.get("/healthz")
    assert page.status_code == 200
    assert "Multi-Venue Control Plane" in page.text
    assert venues.status_code == 200
    assert health.json()["automatic_withdrawals"] is False


def test_settings_persist(tmp_path) -> None:
    settings = tmp_path / "settings.json"
    with TestClient(create_app(settings_path=str(settings))) as client:
        response = client.put("/api/settings", json={"notional_usdt": 2500,"holding_intervals": 4,"min_net_spread_bps": 3,"taker_fee_bps_each_leg": 5,"slippage_bps_each_leg": 2,"max_abs_basis_bps": 100,"depth_multiplier": 1.2,"max_live_notional_usdt": 3000})
        assert response.status_code == 200
    with TestClient(create_app(settings_path=str(settings))) as client:
        assert client.get("/api/settings").json()["settings"]["notional_usdt"] == 2500
