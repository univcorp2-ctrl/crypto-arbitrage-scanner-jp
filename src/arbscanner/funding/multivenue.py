from __future__ import annotations

import asyncio
import math
import os
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from .vault import CredentialVault, VaultUnavailable

try:
    import ccxt.async_support as ccxt_async
except ImportError:  # pragma: no cover - surfaced by runtime readiness
    ccxt_async = None

POLICY_AS_OF = date(2026, 8, 14)


@dataclass(frozen=True, slots=True)
class VenuePolicy:
    id: str
    name: str
    ccxt_id: str | None
    jurisdiction: str
    japan_status: str
    spot: bool
    perpetuals: bool
    funding_api: bool
    private_trading: bool
    live_default: bool
    reason: str
    sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sources"] = list(self.sources)
        return data


VENUES: dict[str, VenuePolicy] = {
    "bitflyer": VenuePolicy(
        "bitflyer", "bitFlyer", None, "JP registered", "domestic_registered",
        True, True, True, True, True,
        "Existing direct adapter: BTC_JPY spot + FX_BTC_JPY Crypto CFD.",
        ("https://lightning.bitflyer.com/docs", "https://jvcea.or.jp/member/"),
    ),
    "mexc": VenuePolicy(
        "mexc", "MEXC", "mexc", "offshore", "product_specific_verification_required",
        True, True, True, True, False,
        "Japan-facing services exist, while some futures products explicitly list Japan as restricted; live use is product/account gated.",
        ("https://www.mexc.com/api-docs/futures/market-endpoints/get-funding-rate", "https://www.mexc.com/announcements/article/introducing-futures-innovation-zone-17827791534000"),
    ),
    "gate": VenuePolicy(
        "gate", "Gate", "gate", "offshore", "product_specific_verification_required",
        True, True, True, True, False,
        "Full spot/perpetual API is available; Japan-resident product eligibility must be verified at account/product level before live routing.",
        ("https://www.gate.com/docs/developers/apiv4/en/", "https://www.gate.com/legal/user-agreement"),
    ),
    "bitrue": VenuePolicy(
        "bitrue", "Bitrue", "bitrue", "offshore", "product_specific_verification_required",
        True, True, True, True, False,
        "Crypto futures and funding APIs exist. TradFi is explicitly restricted in Japan; crypto-futures live use therefore requires current account/product verification.",
        ("https://support.bitrue.com/hc/en-001/articles/6643403350553-OpenAPI-and-Big-Data-Functions-Added-to-Futures", "https://support.bitrue.com/hc/en-001/articles/56552373148313-Important-Disclaimer-TradFi-Futures-Services"),
    ),
    "bitget": VenuePolicy(
        "bitget", "Bitget", "bitget", "offshore", "product_specific_verification_required",
        True, True, True, True, False,
        "The venue currently publishes Japan onboarding pages; derivatives availability remains account/product gated and is not treated as domestic registration.",
        ("https://www.bitget.com/how-to-buy/world-cup-2026-official-song/japan",),
    ),
    "okx": VenuePolicy(
        "okx", "OKX", "okx", "offshore", "restricted_for_japan",
        True, True, True, False, False,
        "OKX compliance disclosure lists Japan as a Restricted Location; public market research only.",
        ("https://www.okx.com/help/risk-compliance-disclosure",),
    ),
    "bingx": VenuePolicy(
        "bingx", "BingX", "bingx", "offshore", "restricted_product",
        True, True, True, False, False,
        "BingX published Japan among restricted CFD regions; public research only until current crypto-perpetual eligibility is independently verified.",
        ("https://bingx.com/en/support/articles/17088995856271",),
    ),
    "gmocoin": VenuePolicy(
        "gmocoin", "GMO Coin", None, "JP registered", "domestic_registered_nonfunding",
        True, False, False, True, False,
        "Domestic leveraged trading/API exists but its carry model is not treated as a symmetric perpetual funding leg.",
        ("https://api.coin.z.com/docs/", "https://jvcea.or.jp/member/"),
    ),
    "bittrade": VenuePolicy(
        "bittrade", "BitTrade", None, "JP registered", "domestic_registered_nonfunding",
        True, False, False, True, False,
        "Domestic spot/leverage venue; used as spot/hedge research, not a perpetual-funding source.",
        ("https://jvcea.or.jp/member/",),
    ),
    "sbivc": VenuePolicy(
        "sbivc", "SBI VC Trade", None, "JP registered", "monitor_only_api_gap",
        True, True, True, False, False,
        "Funding-style leveraged products exist, but a production bot trading API contract is not enabled in this connector release.",
        ("https://jvcea.or.jp/member/",),
    ),
    "bitbank": VenuePolicy(
        "bitbank", "bitbank", None, "JP registered", "spot_only",
        True, False, False, True, False,
        "Spot reference/hedge venue; no selected perpetual funding leg.",
        ("https://github.com/bitbankinc/bitbank-api-docs",),
    ),
    "coincheck": VenuePolicy(
        "coincheck", "Coincheck", None, "JP registered", "spot_only",
        True, False, False, True, False,
        "Spot reference/hedge venue; no selected perpetual funding leg.",
        ("https://coincheck.com/documents/exchange/api",),
    ),
}


@dataclass(slots=True)
class MultiVenueSettings:
    notional_usdt: float = 1_000.0
    holding_intervals: int = 3
    min_net_spread_bps: float = 2.0
    taker_fee_bps_each_leg: float = 6.0
    slippage_bps_each_leg: float = 2.0
    max_abs_basis_bps: float = 150.0
    depth_multiplier: float = 1.2
    max_live_notional_usdt: float = 1_000.0

    @classmethod
    def from_mapping(cls, payload: dict[str, Any] | None) -> "MultiVenueSettings":
        base = cls()
        if not payload:
            return base
        for name in asdict(base):
            if name in payload:
                value = payload[name]
                setattr(base, name, int(value) if name == "holding_intervals" else float(value))
        if base.notional_usdt <= 0 or base.max_live_notional_usdt <= 0:
            raise ValueError("notional must be positive")
        if not 1 <= base.holding_intervals <= 365:
            raise ValueError("holding_intervals must be 1..365")
        return base

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FundingQuote:
    venue: str
    symbol: str
    funding_rate: float
    interval_hours: float
    next_funding_at: str | None
    bid: float
    ask: float
    bid_depth_quote: float
    ask_depth_quote: float
    timestamp: str

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2 if self.bid and self.ask else 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FundingOpportunity:
    strategy: str
    asset: str
    long_venue: str
    short_venue: str
    long_symbol: str
    short_symbol: str
    long_rate: float
    short_rate: float
    spread_rate: float
    estimated_net_bps: float
    estimated_net_usdt: float
    eligible: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["blockers"] = list(self.blockers)
        return data


class ExchangeLike(Protocol):
    id: str
    has: dict[str, Any]
    markets: dict[str, Any]
    async def load_markets(self, reload: bool = False) -> dict[str, Any]: ...
    async def fetch_funding_rate(self, symbol: str) -> dict[str, Any]: ...
    async def fetch_order_book(self, symbol: str, limit: int | None = None) -> dict[str, Any]: ...
    async def fetch_balance(self) -> dict[str, Any]: ...
    async def fetch_positions(self, symbols: list[str] | None = None) -> list[dict[str, Any]]: ...
    async def create_order(self, symbol: str, type: str, side: str, amount: float, price: float | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]: ...
    async def fetch_order(self, id: str, symbol: str | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]: ...
    async def close(self) -> None: ...


def _depth(levels: list[list[float]], limit: int = 20) -> float:
    return sum(float(price) * float(size) for price, size, *_ in levels[:limit])


class CcxtVenueAdapter:
    def __init__(self, venue: str, exchange: ExchangeLike) -> None:
        self.venue = venue
        self.exchange = exchange

    @classmethod
    def create(cls, venue: str, credentials: dict[str, str] | None = None) -> "CcxtVenueAdapter":
        policy = VENUES.get(venue)
        if policy is None or not policy.ccxt_id:
            raise ValueError(f"{venue} does not have a CCXT connector")
        if ccxt_async is None:
            raise RuntimeError("ccxt is not installed")
        exchange_class = getattr(ccxt_async, policy.ccxt_id)
        config: dict[str, Any] = {"enableRateLimit": True, "timeout": 15000}
        if credentials:
            config.update({"apiKey": credentials["api_key"], "secret": credentials["api_secret"]})
        return cls(venue, exchange_class(config))

    async def close(self) -> None:
        await self.exchange.close()

    async def quote(self, symbol: str) -> FundingQuote:
        await self.exchange.load_markets()
        if symbol not in self.exchange.markets:
            raise ValueError(f"{self.venue}: market {symbol} is unavailable")
        funding, book = await asyncio.gather(
            self.exchange.fetch_funding_rate(symbol),
            self.exchange.fetch_order_book(symbol, 20),
        )
        bids, asks = book.get("bids") or [], book.get("asks") or []
        if not bids or not asks:
            raise RuntimeError(f"{self.venue}: empty order book")
        interval = funding.get("interval") or funding.get("fundingInterval") or 8
        try:
            interval_hours = float(interval)
        except (TypeError, ValueError):
            interval_hours = 8.0
        next_ts = funding.get("nextFundingTimestamp")
        next_iso = datetime.fromtimestamp(next_ts / 1000, UTC).isoformat() if next_ts else None
        timestamp = book.get("timestamp") or funding.get("timestamp")
        observed = datetime.fromtimestamp(timestamp / 1000, UTC) if timestamp else datetime.now(UTC)
        return FundingQuote(
            self.venue,
            symbol,
            float(funding.get("fundingRate") or 0.0),
            interval_hours,
            next_iso,
            float(bids[0][0]),
            float(asks[0][0]),
            _depth(bids),
            _depth(asks),
            observed.isoformat(),
        )

    async def private_preflight(self, symbol: str, notional_usdt: float) -> dict[str, Any]:
        await self.exchange.load_markets()
        blockers: list[str] = []
        market = self.exchange.markets.get(symbol)
        if not market:
            blockers.append("market_unavailable")
        elif market.get("active") is False:
            blockers.append("market_inactive")
        if market and not (market.get("swap") or market.get("future") or market.get("spot")):
            blockers.append("unsupported_market_type")
        try:
            balance = await self.exchange.fetch_balance()
        except Exception as exc:
            return {"ready": False, "blockers": ["private_api_failed"], "error": type(exc).__name__}
        free = balance.get("free") or {}
        usdt = float(free.get("USDT") or 0.0)
        if usdt < notional_usdt * 0.15:
            blockers.append("insufficient_usdt_buffer")
        positions: list[dict[str, Any]] = []
        if self.exchange.has.get("fetchPositions"):
            try:
                positions = await self.exchange.fetch_positions([symbol])
            except Exception:
                blockers.append("positions_unavailable")
        return {"ready": not blockers, "blockers": blockers, "free_usdt": usdt, "positions": len(positions)}

    async def fok_order(self, symbol: str, side: str, amount: float, price: float) -> dict[str, Any]:
        params = {"timeInForce": "FOK"}
        order = await self.exchange.create_order(symbol, "limit", side, amount, price, params)
        order_id = str(order.get("id") or "")
        if not order_id:
            raise RuntimeError("exchange returned no order id")
        if self.exchange.has.get("fetchOrder"):
            order = await self.exchange.fetch_order(order_id, symbol)
        status = str(order.get("status") or "").lower()
        filled = float(order.get("filled") or 0.0)
        if status not in {"closed", "filled"} or filled + 1e-12 < amount * 0.999:
            raise RuntimeError(f"FOK order incomplete status={status} filled={filled}")
        return order


def policy_payload() -> dict[str, Any]:
    return {
        "as_of": POLICY_AS_OF.isoformat(),
        "venues": [policy.to_dict() for policy in VENUES.values()],
        "note": "Offshore availability is product/account specific. Public scanning does not imply Japan-resident live eligibility.",
    }


def live_readiness(venue: str, settings: MultiVenueSettings, vault: CredentialVault | None) -> dict[str, Any]:
    policy = VENUES.get(venue)
    blockers: list[str] = []
    if policy is None:
        blockers.append("unknown_venue")
        return {"ready": False, "blockers": blockers}
    if not policy.private_trading or policy.japan_status.startswith("restricted"):
        blockers.append("policy_blocks_private_trading")
    if not os.getenv("FUNDING_MULTI_LIVE_ENABLED", "").lower() in {"1", "true", "yes", "on"}:
        blockers.append("global_live_disabled")
    env_venue = f"FUNDING_{venue.upper()}_LIVE_ENABLED"
    if not os.getenv(env_venue, "").lower() in {"1", "true", "yes", "on"}:
        blockers.append("venue_live_disabled")
    cap = float(os.getenv("FUNDING_MULTI_MAX_LIVE_NOTIONAL_USDT", "0") or 0)
    if cap <= 0 or settings.notional_usdt > min(cap, settings.max_live_notional_usdt):
        blockers.append("notional_exceeds_live_cap")
    attested = os.getenv(f"FUNDING_{venue.upper()}_JP_ELIGIBILITY_ATTESTED", "")
    try:
        attested_date = date.fromisoformat(attested)
        if (date.today() - attested_date).days > 30:
            blockers.append("eligibility_attestation_stale")
    except ValueError:
        blockers.append("eligibility_attestation_missing")
    if vault is None:
        blockers.append("credential_vault_unavailable")
    else:
        status = vault.status(venue)
        if not status.configured or not status.active:
            blockers.append("credentials_missing")
    return {"ready": not blockers, "blockers": blockers, "venue": venue, "policy": policy.to_dict()}


def evaluate_perp_spread(long_quote: FundingQuote, short_quote: FundingQuote, settings: MultiVenueSettings, asset: str = "BTC") -> FundingOpportunity:
    spread = short_quote.funding_rate - long_quote.funding_rate
    gross_bps = spread * 10_000 * settings.holding_intervals
    costs_bps = 4 * (settings.taker_fee_bps_each_leg + settings.slippage_bps_each_leg)
    net_bps = gross_bps - costs_bps
    blockers: list[str] = []
    if long_quote.venue == short_quote.venue:
        blockers.append("same_venue_perp_pair")
    if spread <= 0:
        blockers.append("non_positive_funding_spread")
    if net_bps < settings.min_net_spread_bps:
        blockers.append("net_spread_below_threshold")
    if long_quote.ask_depth_quote < settings.notional_usdt * settings.depth_multiplier:
        blockers.append("insufficient_long_depth")
    if short_quote.bid_depth_quote < settings.notional_usdt * settings.depth_multiplier:
        blockers.append("insufficient_short_depth")
    return FundingOpportunity(
        "perp_perp", asset, long_quote.venue, short_quote.venue,
        long_quote.symbol, short_quote.symbol, long_quote.funding_rate,
        short_quote.funding_rate, spread, net_bps,
        settings.notional_usdt * net_bps / 10_000, not blockers, tuple(blockers),
    )


def evaluate_cash_and_carry(short_quote: FundingQuote, spot_venue: str, spot_symbol: str, spot_ask: float, spot_depth: float, settings: MultiVenueSettings, asset: str = "BTC") -> FundingOpportunity:
    gross_bps = short_quote.funding_rate * 10_000 * settings.holding_intervals
    costs_bps = 4 * (settings.taker_fee_bps_each_leg + settings.slippage_bps_each_leg)
    net_bps = gross_bps - costs_bps
    basis_bps = ((short_quote.bid - spot_ask) / spot_ask * 10_000) if spot_ask else math.inf
    blockers: list[str] = []
    if short_quote.funding_rate <= 0:
        blockers.append("non_positive_short_funding")
    if abs(basis_bps) > settings.max_abs_basis_bps:
        blockers.append("basis_outside_limit")
    if net_bps < settings.min_net_spread_bps:
        blockers.append("net_spread_below_threshold")
    if spot_depth < settings.notional_usdt * settings.depth_multiplier:
        blockers.append("insufficient_spot_depth")
    if short_quote.bid_depth_quote < settings.notional_usdt * settings.depth_multiplier:
        blockers.append("insufficient_short_depth")
    return FundingOpportunity(
        "cash_and_carry", asset, spot_venue, short_quote.venue,
        spot_symbol, short_quote.symbol, 0.0, short_quote.funding_rate,
        short_quote.funding_rate, net_bps,
        settings.notional_usdt * net_bps / 10_000, not blockers, tuple(blockers),
    )


class MultiVenueFundingEngine:
    def __init__(self, settings: MultiVenueSettings | None = None) -> None:
        self.settings = settings or MultiVenueSettings()
        self.kill_switch = True

    async def scan_perpetuals(self, venues: list[str], symbol: str = "BTC/USDT:USDT") -> dict[str, Any]:
        quotes: list[FundingQuote] = []
        errors: dict[str, str] = {}

        async def one(venue: str) -> None:
            policy = VENUES.get(venue)
            if not policy or not policy.ccxt_id or not policy.funding_api:
                return
            adapter = CcxtVenueAdapter.create(venue)
            try:
                quotes.append(await adapter.quote(symbol))
            except Exception as exc:
                errors[venue] = f"{type(exc).__name__}: {str(exc)[:180]}"
            finally:
                await adapter.close()

        await asyncio.gather(*(one(v) for v in venues))
        opportunities: list[FundingOpportunity] = []
        for long_quote in quotes:
            for short_quote in quotes:
                if long_quote.venue != short_quote.venue:
                    opportunities.append(evaluate_perp_spread(long_quote, short_quote, self.settings))
        opportunities.sort(key=lambda item: item.estimated_net_bps, reverse=True)
        return {
            "quotes": [q.to_dict() for q in sorted(quotes, key=lambda q: q.funding_rate)],
            "opportunities": [o.to_dict() for o in opportunities],
            "errors": errors,
            "policy_as_of": POLICY_AS_OF.isoformat(),
        }

    async def execute_perp_spread(self, opportunity: FundingOpportunity, vault: CredentialVault) -> dict[str, Any]:
        if self.kill_switch:
            return {"executed": False, "blockers": ["kill_switch_enabled"]}
        long_ready = live_readiness(opportunity.long_venue, self.settings, vault)
        short_ready = live_readiness(opportunity.short_venue, self.settings, vault)
        blockers = [*long_ready["blockers"], *short_ready["blockers"]]
        if not opportunity.eligible:
            blockers.extend(opportunity.blockers)
        if blockers:
            return {"executed": False, "blockers": sorted(set(blockers))}
        long_creds, short_creds = vault.load(opportunity.long_venue), vault.load(opportunity.short_venue)
        long_adapter = CcxtVenueAdapter.create(opportunity.long_venue, long_creds)
        short_adapter = CcxtVenueAdapter.create(opportunity.short_venue, short_creds)
        try:
            long_quote, short_quote = await asyncio.gather(
                long_adapter.quote(opportunity.long_symbol),
                short_adapter.quote(opportunity.short_symbol),
            )
            amount = self.settings.notional_usdt / max(long_quote.ask, short_quote.bid)
            long_pf, short_pf = await asyncio.gather(
                long_adapter.private_preflight(opportunity.long_symbol, self.settings.notional_usdt),
                short_adapter.private_preflight(opportunity.short_symbol, self.settings.notional_usdt),
            )
            if not long_pf["ready"] or not short_pf["ready"]:
                return {"executed": False, "blockers": [*long_pf["blockers"], *short_pf["blockers"]]}
            slip = self.settings.slippage_bps_each_leg / 10_000
            short_price = short_quote.bid * (1 - slip)
            long_price = long_quote.ask * (1 + slip)
            short_close_price = short_quote.ask * (1 + slip)
            first = await short_adapter.fok_order(opportunity.short_symbol, "sell", amount, short_price)
            try:
                second = await long_adapter.fok_order(opportunity.long_symbol, "buy", amount, long_price)
            except Exception as exc:
                compensation: dict[str, Any] | None = None
                try:
                    compensation = await short_adapter.fok_order(opportunity.short_symbol, "buy", amount, short_close_price)
                except Exception:
                    pass
                return {"executed": False, "blockers": ["second_leg_failed"], "first_order_id": first.get("id"), "compensation_order_id": compensation.get("id") if compensation else None, "error": type(exc).__name__}
            return {"executed": True, "strategy": opportunity.strategy, "amount": amount, "short_order_id": first.get("id"), "long_order_id": second.get("id"), "automatic_withdrawals": False}
        finally:
            await asyncio.gather(long_adapter.close(), short_adapter.close())


def credential_statuses(vault: CredentialVault | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for venue, policy in VENUES.items():
        if vault is None:
            result[venue] = {"venue": venue, "configured": False, "active": False, "secret_values_returned": False}
        else:
            result[venue] = vault.status(venue).to_dict()
        result[venue]["private_trading_supported"] = policy.private_trading
    return result
