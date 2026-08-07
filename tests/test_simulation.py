from __future__ import annotations

from pathlib import Path

from arbscanner.simulation import SimulationEngine, SimulationStore


def test_seeded_store_has_reconciled_dashboard_data(tmp_path: Path) -> None:
    store = SimulationStore(tmp_path / "paper.db")
    store.initialize(seed=42)
    overview = store.overview(
        status={"running": False, "real_order_submission": False},
        risk=SimulationEngine(store).risk,
    )

    assert overview["metrics"]["equity_jpy"] > 0
    assert overview["metrics"]["trade_count"] > 0
    assert len(overview["equity"]) >= 40
    assert len(overview["balances"]["items"]) == 4
    assert overview["data_disclosure"]["real_order_submission"] is False
    store.close()


def test_reset_is_deterministic_for_same_seed(tmp_path: Path) -> None:
    store = SimulationStore(tmp_path / "paper.db")
    store.initialize(seed=7)
    first = store.metrics()
    store.reset(seed=7)
    second = store.metrics()

    assert first["equity_jpy"] == second["equity_jpy"]
    assert first["trade_count"] == second["trade_count"]
    store.close()


def test_engine_rejects_live_mode(tmp_path: Path) -> None:
    store = SimulationStore(tmp_path / "paper.db")
    engine = SimulationEngine(store)
    engine.initialize()

    try:
        engine.set_mode("live")
    except ValueError as exc:
        assert "unsupported mode" in str(exc)
    else:
        raise AssertionError("live mode must never be accepted")
    store.close()
