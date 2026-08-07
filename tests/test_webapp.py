from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from arbscanner.webapp import create_app


def test_dashboard_and_api_are_available(tmp_path: Path) -> None:
    app = create_app(db_path=str(tmp_path / "web.db"), autostart=False)
    with TestClient(app) as client:
        root = client.get("/")
        overview = client.get("/api/overview")
        exchanges = client.get("/api/exchanges")

        assert root.status_code == 200
        assert "ARB OPS" in root.text
        assert overview.status_code == 200
        assert overview.json()["status"]["real_order_submission"] is False
        assert exchanges.status_code == 200
        assert exchanges.json()["secret_values_returned"] is False


def test_risk_and_kill_switch_controls(tmp_path: Path) -> None:
    app = create_app(db_path=str(tmp_path / "web.db"), autostart=False)
    with TestClient(app) as client:
        risk = client.put("/api/risk", json={"max_notional_jpy": 25000})
        kill = client.put("/api/kill-switch", json={"enabled": True})
        invalid_mode = client.put("/api/mode", json={"mode": "live"})

        assert risk.status_code == 200
        assert risk.json()["risk"]["max_notional_jpy"] == 25000
        assert kill.json()["kill_switch"] is True
        assert invalid_mode.status_code == 422
