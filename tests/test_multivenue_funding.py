from __future__ import annotations

from datetime import date

from arbscanner.funding.multivenue import (
    FundingQuote,
    MultiVenueSettings,
    VENUES,
    evaluate_perp_spread,
    live_readiness,
    policy_payload,
)


def quote(venue: str, rate: float) -> FundingQuote:
    return FundingQuote(venue, "BTC/USDT:USDT", rate, 8, None, 99_990, 100_010, 1_000_000, 1_000_000, "2026-08-14T00:00:00+00:00")


def test_policy_has_requested_global_venues() -> None:
    assert {"mexc", "gate", "bitrue", "bitget"}.issubset(VENUES)
    assert VENUES["okx"].private_trading is False
    assert policy_payload()["as_of"] == "2026-08-14"


def test_perp_spread_opportunity_math() -> None:
    settings = MultiVenueSettings(holding_intervals=3, min_net_spread_bps=1, taker_fee_bps_each_leg=1, slippage_bps_each_leg=1)
    result = evaluate_perp_spread(quote("mexc", -0.0001), quote("gate", 0.0005), settings)
    assert result.spread_rate == 0.0006
    assert result.estimated_net_bps == 10.0
    assert result.eligible is True


def test_same_venue_is_blocked() -> None:
    result = evaluate_perp_spread(quote("gate", 0.0), quote("gate", 0.001), MultiVenueSettings(taker_fee_bps_each_leg=0, slippage_bps_each_leg=0))
    assert not result.eligible
    assert "same_venue_perp_pair" in result.blockers


def test_live_readiness_is_fail_closed(monkeypatch) -> None:
    monkeypatch.delenv("FUNDING_MULTI_LIVE_ENABLED", raising=False)
    result = live_readiness("mexc", MultiVenueSettings(), None)
    assert not result["ready"]
    assert "global_live_disabled" in result["blockers"]
    assert "credential_vault_unavailable" in result["blockers"]


def test_restricted_venue_cannot_be_live(monkeypatch) -> None:
    monkeypatch.setenv("FUNDING_MULTI_LIVE_ENABLED", "true")
    monkeypatch.setenv("FUNDING_OKX_LIVE_ENABLED", "true")
    monkeypatch.setenv("FUNDING_MULTI_MAX_LIVE_NOTIONAL_USDT", "10000")
    monkeypatch.setenv("FUNDING_OKX_JP_ELIGIBILITY_ATTESTED", date.today().isoformat())
    result = live_readiness("okx", MultiVenueSettings(), None)
    assert "policy_blocks_private_trading" in result["blockers"]
