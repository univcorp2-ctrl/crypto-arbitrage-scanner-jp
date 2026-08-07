from __future__ import annotations

from arbscanner.analytics import calculate_metrics, daily_equity_points


def test_daily_equity_uses_last_snapshot_per_day() -> None:
    points = [
        {"recorded_at": "2026-01-01T01:00:00+00:00", "equity_jpy": 100.0},
        {"recorded_at": "2026-01-01T23:00:00+00:00", "equity_jpy": 101.0},
        {"recorded_at": "2026-01-02T23:00:00+00:00", "equity_jpy": 99.0},
        {"recorded_at": "2026-01-03T23:00:00+00:00", "equity_jpy": 103.0},
    ]

    daily = daily_equity_points(points)

    assert [item["equity_jpy"] for item in daily] == [101.0, 99.0, 103.0]
    assert daily[1]["drawdown"] < 0


def test_metrics_include_risk_and_execution_costs() -> None:
    points = [
        {"recorded_at": "2026-01-01T00:00:00+00:00", "equity_jpy": 100.0},
        {"recorded_at": "2026-01-02T00:00:00+00:00", "equity_jpy": 102.0},
        {"recorded_at": "2026-01-03T00:00:00+00:00", "equity_jpy": 101.0},
        {"recorded_at": "2026-01-04T00:00:00+00:00", "equity_jpy": 104.0},
    ]
    trades = [
        {
            "net_pnl_jpy": 4.0,
            "fees_jpy": 1.0,
            "slippage_jpy": 0.5,
            "rebalance_reserve_jpy": 0.25,
        },
        {
            "net_pnl_jpy": -1.0,
            "fees_jpy": 0.5,
            "slippage_jpy": 0.2,
            "rebalance_reserve_jpy": 0.1,
        },
    ]

    metrics = calculate_metrics(points, trades)

    assert metrics["total_return"] == 0.04
    assert metrics["max_drawdown"] < 0
    assert metrics["sharpe_ratio"] is not None
    assert metrics["win_rate"] == 0.5
    assert metrics["profit_factor"] == 4.0
    assert metrics["fees_jpy"] == 1.5
