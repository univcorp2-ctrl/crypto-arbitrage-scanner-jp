from __future__ import annotations

from fastapi.testclient import TestClient

from arbscanner.web import create_app


def test_dashboard_exposes_seeded_paper_state(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "paper.db", autostart=False)

    with TestClient(app) as client:
        response = client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "paper"
    assert payload["risk"]["live_order_routing"] is False
    assert payload["performance"]["trade_count"] == 30
    assert len(payload["assets"]) == 4
    assert all("credential_status" in item for item in payload["exchanges"])


def test_settings_and_kill_switch_are_persisted(tmp_path) -> None:
    app = create_app(db_path=tmp_path / "paper.db", autostart=False)

    with TestClient(app) as client:
        settings_response = client.put(
            "/api/settings/paper",
            json={
                "min_net_bps": 20,
                "max_trade_jpy": 30000,
                "min_trade_jpy": 2000,
                "slippage_bps": 3,
                "rebalance_reserve_bps": 4,
                "interval_seconds": 60,
            },
        )
        switch_response = client.post(
            "/api/risk/kill-switch",
            json={"enabled": True},
        )
        dashboard = client.get("/api/dashboard").json()

    assert settings_response.status_code == 200
    assert switch_response.status_code == 200
    assert dashboard["engine"]["settings"]["min_net_bps"] == 20
    assert dashboard["risk"]["kill_switch"] is True
