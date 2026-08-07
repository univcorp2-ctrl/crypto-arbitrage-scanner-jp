import json
from pathlib import Path


def test_dashboard_seed_has_required_sections() -> None:
    path = Path("docs/data/dashboard.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    required = {
        "generated_at",
        "mode",
        "data_status",
        "metrics",
        "balances",
        "trades",
        "equity_history",
        "daily",
        "exchanges",
        "connectors",
        "risk",
        "system",
    }
    assert required <= payload.keys()
    assert payload["mode"] == "paper"
    assert payload["risk"]["live_order_enabled"] is False
