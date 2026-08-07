from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class LiveEligibility(StrEnum):
    FUNDING_CANDIDATE = "funding_candidate"
    SPOT_HEDGE_ONLY = "spot_hedge_only"
    RESEARCH_ONLY = "research_only"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class VenuePolicy:
    venue_id: str
    display_name: str
    registered_in_japan: bool
    eligibility: LiveEligibility
    spot_available: bool
    variable_funding_available: bool
    products: tuple[str, ...]
    reason: str
    reviewed_on: str = "2026-08-08"

    @property
    def japan_live_allowed(self) -> bool:
        return self.registered_in_japan and self.eligibility in {
            LiveEligibility.FUNDING_CANDIDATE,
            LiveEligibility.SPOT_HEDGE_ONLY,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue_id": self.venue_id,
            "display_name": self.display_name,
            "registered_in_japan": self.registered_in_japan,
            "japan_live_allowed": self.japan_live_allowed,
            "eligibility": self.eligibility.value,
            "spot_available": self.spot_available,
            "variable_funding_available": self.variable_funding_available,
            "products": list(self.products),
            "reason": self.reason,
            "reviewed_on": self.reviewed_on,
        }


VENUE_POLICIES: dict[str, VenuePolicy] = {
    "bitflyer": VenuePolicy(
        venue_id="bitflyer",
        display_name="bitFlyer",
        registered_in_japan=True,
        eligibility=LiveEligibility.FUNDING_CANDIDATE,
        spot_available=True,
        variable_funding_available=True,
        products=("BTC_JPY", "FX_BTC_JPY"),
        reason="Registered domestic venue with BTC/JPY spot and Crypto CFD funding API.",
    ),
    "bitbank": VenuePolicy(
        venue_id="bitbank",
        display_name="bitbank",
        registered_in_japan=True,
        eligibility=LiveEligibility.SPOT_HEDGE_ONLY,
        spot_available=True,
        variable_funding_available=False,
        products=("BTC_JPY",),
        reason="Domestic spot venue; usable as a pre-funded hedge leg, not a funding leg.",
    ),
    "gmo_coin": VenuePolicy(
        venue_id="gmo_coin",
        display_name="GMOコイン",
        registered_in_japan=True,
        eligibility=LiveEligibility.SPOT_HEDGE_ONLY,
        spot_available=True,
        variable_funding_available=False,
        products=("BTC_JPY",),
        reason="Domestic venue; derivative leverage fee is modeled as a cost, not funding income.",
    ),
    "coincheck": VenuePolicy(
        venue_id="coincheck",
        display_name="Coincheck",
        registered_in_japan=True,
        eligibility=LiveEligibility.SPOT_HEDGE_ONLY,
        spot_available=True,
        variable_funding_available=False,
        products=("BTC_JPY",),
        reason="Domestic spot venue; no variable perpetual funding leg enabled by this project.",
    ),
    "okj": VenuePolicy(
        venue_id="okj",
        display_name="OKJ",
        registered_in_japan=True,
        eligibility=LiveEligibility.SPOT_HEDGE_ONLY,
        spot_available=True,
        variable_funding_available=False,
        products=("BTC_JPY",),
        reason="Registered domestic spot venue; connector remains read-only until tested.",
    ),
    "binance_japan": VenuePolicy(
        venue_id="binance_japan",
        display_name="Binance Japan",
        registered_in_japan=True,
        eligibility=LiveEligibility.SPOT_HEDGE_ONLY,
        spot_available=True,
        variable_funding_available=False,
        products=("BTC_JPY",),
        reason="Japan entity is treated as spot-only; global futures are not enabled for Japan profile.",
    ),
    "bybit": VenuePolicy(
        venue_id="bybit",
        display_name="Bybit",
        registered_in_japan=False,
        eligibility=LiveEligibility.RESEARCH_ONLY,
        spot_available=False,
        variable_funding_available=True,
        products=(),
        reason="Research data only for Japan profile because of FSA unregistered-service warning.",
    ),
    "bitget": VenuePolicy(
        venue_id="bitget",
        display_name="Bitget",
        registered_in_japan=False,
        eligibility=LiveEligibility.RESEARCH_ONLY,
        spot_available=False,
        variable_funding_available=True,
        products=(),
        reason="Research data only for Japan profile because of FSA unregistered-service warning.",
    ),
    "mexc": VenuePolicy(
        venue_id="mexc",
        display_name="MEXC",
        registered_in_japan=False,
        eligibility=LiveEligibility.RESEARCH_ONLY,
        spot_available=False,
        variable_funding_available=True,
        products=(),
        reason="Research data only; live routing is disabled for Japan profile.",
    ),
    "kucoin": VenuePolicy(
        venue_id="kucoin",
        display_name="KuCoin",
        registered_in_japan=False,
        eligibility=LiveEligibility.RESEARCH_ONLY,
        spot_available=False,
        variable_funding_available=True,
        products=(),
        reason="Research data only; live routing is disabled for Japan profile.",
    ),
}


def get_policy(venue_id: str) -> VenuePolicy:
    try:
        return VENUE_POLICIES[venue_id]
    except KeyError as exc:
        raise ValueError(f"unknown venue: {venue_id}") from exc


def assert_funding_live_allowed(venue_id: str) -> VenuePolicy:
    policy = get_policy(venue_id)
    if not (
        policy.registered_in_japan
        and policy.eligibility is LiveEligibility.FUNDING_CANDIDATE
        and policy.variable_funding_available
    ):
        raise PermissionError(f"funding live routing is disabled for {venue_id}")
    return policy


def policy_payload() -> dict[str, Any]:
    return {
        "jurisdiction_profile": "JP_RESIDENT",
        "reviewed_on": "2026-08-08",
        "automatic_withdrawals": False,
        "external_transfers": False,
        "items": [policy.to_dict() for policy in VENUE_POLICIES.values()],
    }
