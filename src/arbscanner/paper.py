from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from .analytics import calculate_metrics
from .config import ScannerConfig, load_config
from .exchange_registry import public_exchange_registry
from .models import ExchangeConfig, Opportunity, OrderBook, PriceLevel
from .scanner import calculate_opportunities, fetch_orderbooks
from .storage import PaperStore

BPS = Decimal("10000")
ONE = Decimal("1")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_decimal(name: str, default: str) -> Decimal:
    value = os.getenv(name)
    return Decimal(value) if value else Decimal(default)


@dataclass
class PaperSettings:
    min_net_bps: Decimal = Decimal("12")
    max_trade_jpy: Decimal = Decimal("50000")
    min_trade_jpy: Decimal = Decimal("2000")
    slippage_bps: Decimal = Decimal("2")
    rebalance_reserve_bps: Decimal = Decimal("3")
    interval_seconds: int = 30
    autostart: bool = True

    @classmethod
    def from_env(cls) -> PaperSettings:
        return cls(
            min_net_bps=_env_decimal("ARB_MIN_NET_BPS", "12"),
            max_trade_jpy=_env_decimal("ARB_MAX_TRADE_JPY", "50000"),
            min_trade_jpy=_env_decimal("ARB_MIN_TRADE_JPY", "2000"),
            slippage_bps=_env_decimal("ARB_SLIPPAGE_BPS", "2"),
            rebalance_reserve_bps=_env_decimal("ARB_REBALANCE_RESERVE_BPS", "3"),
            interval_seconds=max(5, int(os.getenv("ARB_INTERVAL_SECONDS", "30"))),
            autostart=_env_bool("ARB_AUTOSTART_PAPER", True),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "min_net_bps": float(self.min_net_bps),
            "max_trade_jpy": float(self.max_trade_jpy),
            "min_trade_jpy": float(self.min_trade_jpy),
            "slippage_bps": float(self.slippage_bps),
            "rebalance_reserve_bps": float(self.rebalance_reserve_bps),
            "interval_seconds": self.interval_seconds,
            "autostart": self.autostart,
        }


def plan_paper_trade(
    opportunity: Opportunity,
    exchange_configs: tuple[ExchangeConfig, ...],
    balances: dict[tuple[str, str], Decimal],
    settings: PaperSettings,
) -> dict[str, Any] | None:
    fee_rates = {item.name: item.taker_fee_rate for item in exchange_configs}
    buy_fee_rate = fee_rates.get(opportunity.buy_exchange, Decimal("0"))
    sell_fee_rate = fee_rates.get(opportunity.sell_exchange, Decimal("0"))
    available_jpy = balances.get((opportunity.buy_exchange, "JPY"), Decimal("0"))
    available_btc = balances.get((opportunity.sell_exchange, "BTC"), Decimal("0"))

    conservative_rate = (
        ONE + buy_fee_rate + settings.slippage_bps / BPS + settings.rebalance_reserve_bps / BPS
    )
    max_by_cash = available_jpy / (opportunity.buy_ask * conservative_rate)
    max_by_limit = settings.max_trade_jpy / opportunity.buy_ask
    quantity = min(opportunity.top_size, available_btc, max_by_cash, max_by_limit)
    quantity = quantity.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    if quantity <= 0:
        return None

    buy_notional = opportunity.buy_ask * quantity
    sell_notional = opportunity.sell_bid * quantity
    if buy_notional < settings.min_trade_jpy:
        return None

    buy_fee = buy_notional * buy_fee_rate
    sell_fee = sell_notional * sell_fee_rate
    slippage = ((buy_notional + sell_notional) / Decimal("2")) * (settings.slippage_bps / BPS)
    reserve = ((buy_notional + sell_notional) / Decimal("2")) * (
        settings.rebalance_reserve_bps / BPS
    )
    buy_debit = buy_notional + buy_fee + slippage / 2 + reserve / 2
    sell_credit = sell_notional - sell_fee - slippage / 2 - reserve / 2
    net_pnl = sell_credit - buy_debit
    if net_pnl <= 0 or buy_debit > available_jpy:
        return None

    net_spread_bps = net_pnl / buy_debit * BPS
    if net_spread_bps < settings.min_net_bps:
        return None

    return {
        "market": opportunity.market,
        "buy_exchange": opportunity.buy_exchange,
        "sell_exchange": opportunity.sell_exchange,
        "quantity_btc": float(quantity),
        "buy_price_jpy": float(opportunity.buy_ask),
        "sell_price_jpy": float(opportunity.sell_bid),
        "buy_notional_jpy": float(buy_notional),
        "sell_notional_jpy": float(sell_notional),
        "buy_debit_jpy": float(buy_debit),
        "sell_credit_jpy": float(sell_credit),
        "gross_pnl_jpy": float(sell_notional - buy_notional),
        "fees_jpy": float(buy_fee + sell_fee),
        "slippage_jpy": float(slippage),
        "rebalance_reserve_jpy": float(reserve),
        "net_pnl_jpy": float(net_pnl),
        "net_spread_bps": float(net_spread_bps),
    }


class PaperTradingService:
    def __init__(self, store: PaperStore, settings: PaperSettings | None = None) -> None:
        self.store = store
        self.store.initialize()
        self.settings = settings or PaperSettings.from_env()
        self._load_persisted_settings()
        self.config = self._load_scanner_config()
        self.running = False
        self._task: asyncio.Task[None] | None = None
        self._run_lock = asyncio.Lock()
        self.last_run_at: str | None = None
        self.last_result: dict[str, Any] | None = None

    def _load_persisted_settings(self) -> None:
        decimal_fields = (
            "min_net_bps",
            "max_trade_jpy",
            "min_trade_jpy",
            "slippage_bps",
            "rebalance_reserve_bps",
        )
        for field in decimal_fields:
            value = self.store.get_setting(f"paper.{field}")
            if value is not None:
                setattr(self.settings, field, Decimal(value))
        interval = self.store.get_setting("paper.interval_seconds")
        if interval is not None:
            self.settings.interval_seconds = max(5, int(interval))

    def _load_scanner_config(self) -> ScannerConfig:
        config_path = Path(os.getenv("ARB_CONFIG_PATH", "config.yml"))
        if config_path.exists():
            try:
                return load_config(config_path)
            except (OSError, ValueError) as exc:
                self.store.record_event(
                    level="warning",
                    kind="config_fallback",
                    message="設定ファイルを読めないため安全な内蔵設定を使用します。",
                    details={"path": str(config_path), "error": str(exc)},
                )
        return ScannerConfig(
            market="BTC/JPY",
            min_net_bps=self.settings.min_net_bps,
            request_timeout_seconds=8.0,
            exchanges=(
                ExchangeConfig("bitbank", True, "btc_jpy", Decimal("10")),
                ExchangeConfig("gmocoin", True, "BTC", Decimal("5")),
                ExchangeConfig("bitflyer", True, "BTC_JPY", Decimal("15")),
                ExchangeConfig("coincheck", True, "btc_jpy", Decimal("0")),
            ),
        )

    async def start(self) -> dict[str, Any]:
        if self.running:
            return {"running": True, "message": "ペーパーエンジンは既に稼働中です。"}
        if self.kill_switch_enabled:
            return {"running": False, "message": "停止スイッチが有効です。"}
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="arb-paper-loop")
        self.store.record_event(
            level="info",
            kind="paper_started",
            message="ペーパートレードエンジンを開始しました。",
        )
        return {"running": True, "message": "ペーパートレードを開始しました。"}

    async def stop(self) -> dict[str, Any]:
        self.running = False
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.store.record_event(
            level="info",
            kind="paper_stopped",
            message="ペーパートレードエンジンを停止しました。",
        )
        return {"running": False, "message": "ペーパートレードを停止しました。"}

    async def _loop(self) -> None:
        while self.running:
            try:
                await self.run_once()
            except Exception as exc:
                self.store.record_event(
                    level="error",
                    kind="paper_loop_error",
                    message="ペーパーサイクルでエラーが発生しました。",
                    details={"error": str(exc)},
                )
            await asyncio.sleep(self.settings.interval_seconds)

    @property
    def kill_switch_enabled(self) -> bool:
        return self.store.get_setting("risk.kill_switch") == "true"

    async def set_kill_switch(self, enabled: bool) -> dict[str, Any]:
        self.store.set_setting("risk.kill_switch", "true" if enabled else "false")
        if enabled and self.running:
            await self.stop()
        self.store.record_event(
            level="warning" if enabled else "info",
            kind="kill_switch",
            message="停止スイッチを有効化しました。" if enabled else "停止スイッチを解除しました。",
        )
        return {"enabled": enabled, "running": self.running}

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        for field in (
            "min_net_bps",
            "max_trade_jpy",
            "min_trade_jpy",
            "slippage_bps",
            "rebalance_reserve_bps",
        ):
            value = Decimal(str(values[field]))
            setattr(self.settings, field, value)
            self.store.set_setting(f"paper.{field}", str(value))
        interval = max(5, int(values["interval_seconds"]))
        self.settings.interval_seconds = interval
        self.store.set_setting("paper.interval_seconds", str(interval))
        self.store.record_event(
            level="info",
            kind="settings_updated",
            message="ペーパー運用設定を更新しました。",
            details=self.settings.as_dict(),
        )
        return self.settings.as_dict()

    async def run_once(self) -> dict[str, Any]:
        async with self._run_lock:
            now = datetime.now(UTC).replace(microsecond=0)
            if self.kill_switch_enabled:
                result = {
                    "status": "blocked_by_kill_switch",
                    "recorded_at": now.isoformat(),
                    "data_source": "none",
                    "books": [],
                    "opportunities": [],
                    "execution": None,
                    "errors": {},
                }
                self.last_result = result
                self.last_run_at = now.isoformat()
                return result

            books, errors = await fetch_orderbooks(self.config)
            data_source = "live_public_orderbooks"
            if len(books) < 2:
                books = self._synthetic_books()
                data_source = "simulated_research_snapshot"

            threshold = (
                self.settings.min_net_bps
                + self.settings.slippage_bps
                + self.settings.rebalance_reserve_bps
            )
            opportunities = calculate_opportunities(
                books,
                self.config.exchanges,
                min_net_bps=threshold,
            )
            balances = {key: Decimal(str(value)) for key, value in self.store.balance_map().items()}
            plan = None
            for opportunity in opportunities:
                plan = plan_paper_trade(
                    opportunity,
                    self.config.exchanges,
                    balances,
                    self.settings,
                )
                if plan is not None:
                    break

            reference_price = self._reference_price(books)
            execution = None
            if plan is not None:
                execution = self._execute_plan(
                    plan=plan,
                    balances=balances,
                    reference_price=reference_price,
                    data_source=data_source,
                    timestamp=now,
                )
            else:
                self._record_mark_to_market(
                    balances=balances,
                    reference_price=reference_price,
                    data_source=data_source,
                    timestamp=now,
                )

            result = {
                "status": "simulated_trade" if execution else "no_trade",
                "recorded_at": now.isoformat(),
                "data_source": data_source,
                "books": self._book_summaries(books),
                "opportunities": [self._opportunity_dict(item) for item in opportunities[:20]],
                "execution": execution,
                "errors": errors,
            }
            self.last_result = result
            self.last_run_at = now.isoformat()
            self.store.record_event(
                level="info" if not errors else "warning",
                kind="paper_cycle",
                message=(
                    "ペーパー約定を記録しました。"
                    if execution
                    else "板を確認しましたが執行条件には達しませんでした。"
                ),
                details={
                    "data_source": data_source,
                    "opportunity_count": len(opportunities),
                    "errors": errors,
                },
            )
            return result

    def _execute_plan(
        self,
        *,
        plan: dict[str, Any],
        balances: dict[tuple[str, str], Decimal],
        reference_price: Decimal,
        data_source: str,
        timestamp: datetime,
    ) -> dict[str, Any]:
        buy_exchange = str(plan["buy_exchange"])
        sell_exchange = str(plan["sell_exchange"])
        quantity = Decimal(str(plan["quantity_btc"]))
        buy_debit = Decimal(str(plan["buy_debit_jpy"]))
        sell_credit = Decimal(str(plan["sell_credit_jpy"]))

        balances[(buy_exchange, "JPY")] -= buy_debit
        balances[(buy_exchange, "BTC")] = (
            balances.get((buy_exchange, "BTC"), Decimal("0")) + quantity
        )
        balances[(sell_exchange, "BTC")] -= quantity
        balances[(sell_exchange, "JPY")] = (
            balances.get((sell_exchange, "JPY"), Decimal("0")) + sell_credit
        )

        cash = sum(amount for (exchange, asset), amount in balances.items() if asset == "JPY")
        btc = sum(amount for (exchange, asset), amount in balances.items() if asset == "BTC")
        crypto_value = btc * reference_price
        equity = cash + crypto_value
        executed_at = timestamp.isoformat()
        trade = {
            "executed_at": executed_at,
            "market": str(plan["market"]),
            "buy_exchange": buy_exchange,
            "sell_exchange": sell_exchange,
            "quantity_btc": float(quantity),
            "buy_price_jpy": float(plan["buy_price_jpy"]),
            "sell_price_jpy": float(plan["sell_price_jpy"]),
            "gross_pnl_jpy": float(plan["gross_pnl_jpy"]),
            "fees_jpy": float(plan["fees_jpy"]),
            "slippage_jpy": float(plan["slippage_jpy"]),
            "rebalance_reserve_jpy": float(plan["rebalance_reserve_jpy"]),
            "net_pnl_jpy": float(plan["net_pnl_jpy"]),
            "net_spread_bps": float(plan["net_spread_bps"]),
            "status": "simulated_filled",
            "source": data_source,
        }
        updates = {key: float(value) for key, value in balances.items()}
        snapshot = {
            "recorded_at": executed_at,
            "equity_jpy": float(equity),
            "cash_jpy": float(cash),
            "crypto_jpy": float(crypto_value),
            "reference_price_jpy": float(reference_price),
            "daily_pnl_jpy": float(plan["net_pnl_jpy"]),
            "data_source": data_source,
        }
        self.store.record_trade_and_state(
            trade=trade,
            balance_updates=updates,
            equity=snapshot,
        )
        return trade

    def _record_mark_to_market(
        self,
        *,
        balances: dict[tuple[str, str], Decimal],
        reference_price: Decimal,
        data_source: str,
        timestamp: datetime,
    ) -> None:
        cash = sum(amount for (_, asset), amount in balances.items() if asset == "JPY")
        btc = sum(amount for (_, asset), amount in balances.items() if asset == "BTC")
        crypto_value = btc * reference_price
        self.store.record_equity(
            {
                "recorded_at": timestamp.isoformat(),
                "equity_jpy": float(cash + crypto_value),
                "cash_jpy": float(cash),
                "crypto_jpy": float(crypto_value),
                "reference_price_jpy": float(reference_price),
                "daily_pnl_jpy": 0.0,
                "data_source": data_source,
            }
        )

    def _reference_price(self, books: list[OrderBook]) -> Decimal:
        mids = [
            (book.best_bid.price + book.best_ask.price) / 2
            for book in books
            if book.best_bid is not None and book.best_ask is not None
        ]
        if mids:
            return sum(mids, Decimal("0")) / Decimal(len(mids))
        latest = self.store.latest_equity()
        return Decimal(str(latest["reference_price_jpy"] if latest else 10_200_000))

    def _synthetic_books(self) -> list[OrderBook]:
        latest = self.store.latest_equity()
        reference = Decimal(str(latest["reference_price_jpy"] if latest else 10_200_000))
        cycle = int(datetime.now(UTC).timestamp() // 60) % 5
        normal_shifts = {
            "bitbank": Decimal("-2"),
            "gmocoin": Decimal("1"),
            "bitflyer": Decimal("-1"),
            "coincheck": Decimal("2"),
        }
        opportunity_shifts = {
            "bitbank": Decimal("-22"),
            "gmocoin": Decimal("24"),
            "bitflyer": Decimal("0"),
            "coincheck": Decimal("3"),
        }
        shifts = opportunity_shifts if cycle == 0 else normal_shifts
        spread_bps = Decimal("4")
        books: list[OrderBook] = []
        for index, config in enumerate(self.config.exchanges):
            if not config.enabled:
                continue
            mid_shift = shifts.get(config.name, Decimal("0"))
            bid = reference * (ONE + (mid_shift - spread_bps / 2) / BPS)
            ask = reference * (ONE + (mid_shift + spread_bps / 2) / BPS)
            amount = Decimal("0.012") + Decimal(index) * Decimal("0.002")
            books.append(
                OrderBook(
                    exchange=config.name,
                    market=self.config.market,
                    raw_symbol=config.pair,
                    bids=(PriceLevel(price=bid, amount=amount),),
                    asks=(PriceLevel(price=ask, amount=amount),),
                    timestamp=datetime.now(UTC).replace(microsecond=0).isoformat(),
                )
            )
        return books

    @staticmethod
    def _book_summaries(books: list[OrderBook]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for book in books:
            if book.best_bid is None or book.best_ask is None:
                continue
            result.append(
                {
                    "exchange": book.exchange,
                    "market": book.market,
                    "best_bid": float(book.best_bid.price),
                    "best_ask": float(book.best_ask.price),
                    "bid_size": float(book.best_bid.amount),
                    "ask_size": float(book.best_ask.amount),
                    "timestamp": book.timestamp,
                }
            )
        return result

    @staticmethod
    def _opportunity_dict(opportunity: Opportunity) -> dict[str, Any]:
        return {
            "market": opportunity.market,
            "buy_exchange": opportunity.buy_exchange,
            "sell_exchange": opportunity.sell_exchange,
            "buy_ask": float(opportunity.buy_ask),
            "sell_bid": float(opportunity.sell_bid),
            "top_size": float(opportunity.top_size),
            "gross_spread_bps": float(opportunity.gross_spread_bps),
            "net_spread_bps": float(opportunity.net_spread_bps),
            "net_profit_quote": float(opportunity.net_profit_quote),
        }

    def dashboard_payload(self) -> dict[str, Any]:
        equity = self.store.list_equity()
        trades = self.store.list_trades()
        performance = calculate_metrics(equity, trades)
        latest = equity[-1] if equity else None
        reference_price = float(latest["reference_price_jpy"]) if latest else 0.0
        balances = self._asset_rows(reference_price)
        exchanges = public_exchange_registry()
        error_by_exchange = (self.last_result or {}).get("errors", {})
        for venue in exchanges:
            venue["runtime_status"] = "error" if venue["id"] in error_by_exchange else "ready"
            venue["last_error"] = error_by_exchange.get(venue["id"])

        return {
            "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "mode": "paper",
            "mode_label": "SIMULATED / 実注文なし",
            "engine": {
                "running": self.running,
                "last_run_at": self.last_run_at,
                "settings": self.settings.as_dict(),
            },
            "risk": {
                "kill_switch": self.kill_switch_enabled,
                "live_order_routing": False,
                "withdrawal_routing": False,
                "secret_values_exposed": False,
                "default_bind": "127.0.0.1",
            },
            "performance": performance,
            "equity": equity,
            "assets": balances,
            "trades": trades,
            "exchanges": exchanges,
            "last_cycle": self.last_result,
            "events": self.store.list_events(),
            "data_disclosure": {
                "seeded_history": "seeded_research_demo",
                "live_market_data": "各取引所の公開板。失敗時は明示的な模擬スナップショット。",
                "execution": "全約定はペーパー計算であり、取引所へ注文を送信しません。",
            },
        }

    def _asset_rows(self, reference_price: float) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, float]] = {}
        for row in self.store.list_balances():
            venue = str(row["exchange"])
            grouped.setdefault(venue, {"JPY": 0.0, "BTC": 0.0})
            grouped[venue][str(row["asset"])] = float(row["amount"])
        total_btc = sum(values["BTC"] for values in grouped.values())
        target_btc = total_btc / len(grouped) if grouped else 0.0
        totals = {
            venue: values["JPY"] + values["BTC"] * reference_price
            for venue, values in grouped.items()
        }
        grand_total = sum(totals.values())
        return [
            {
                "exchange": venue,
                "jpy": values["JPY"],
                "btc": values["BTC"],
                "btc_value_jpy": values["BTC"] * reference_price,
                "total_jpy": totals[venue],
                "allocation": totals[venue] / grand_total if grand_total else 0.0,
                "btc_vs_equal_target": values["BTC"] - target_btc,
            }
            for venue, values in sorted(grouped.items())
        ]
