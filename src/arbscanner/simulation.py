from __future__ import annotations

import asyncio
import contextlib
import math
import random
import sqlite3
import statistics
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

from .config import load_config
from .models import Opportunity
from .scanner import calculate_opportunities, fetch_orderbooks

EXCHANGE_IDS = ("bitbank", "gmocoin", "bitflyer", "coincheck")
DEFAULT_FEE_RATES = {
    "bitbank": 0.0010,
    "gmocoin": 0.0005,
    "bitflyer": 0.0015,
    "coincheck": 0.0,
}
VALID_MODES = {"public-live-paper", "synthetic-replay"}


@dataclass(frozen=True)
class RiskLimits:
    min_net_bps: float = 8.0
    max_notional_jpy: float = 100_000.0
    max_daily_loss_jpy: float = 50_000.0
    max_slippage_bps: float = 4.0
    min_jpy_reserve: float = 100_000.0
    min_btc_reserve: float = 0.002


class SimulationStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()

    def initialize(self, *, seed: int = 20260807) -> None:
        with self._lock:
            self._connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS balances (
                    exchange TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    amount REAL NOT NULL,
                    PRIMARY KEY (exchange, asset)
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    market TEXT NOT NULL,
                    buy_exchange TEXT NOT NULL,
                    sell_exchange TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    buy_price REAL NOT NULL,
                    sell_price REAL NOT NULL,
                    gross_bps REAL NOT NULL,
                    net_bps REAL NOT NULL,
                    fees_jpy REAL NOT NULL,
                    slippage_bps REAL NOT NULL,
                    latency_ms REAL NOT NULL,
                    pnl_jpy REAL NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades(ts DESC);
                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    equity_jpy REAL NOT NULL,
                    period_pnl_jpy REAL NOT NULL,
                    drawdown_pct REAL NOT NULL,
                    reference_price_jpy REAL NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity_snapshots(ts ASC);
                CREATE TABLE IF NOT EXISTS opportunities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    buy_exchange TEXT NOT NULL,
                    sell_exchange TEXT NOT NULL,
                    buy_ask REAL NOT NULL,
                    sell_bid REAL NOT NULL,
                    net_bps REAL NOT NULL,
                    executable_notional_jpy REAL NOT NULL,
                    source TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_opportunities_ts
                    ON opportunities(ts DESC);
                """
            )
            row = self._connection.execute("SELECT COUNT(*) AS count FROM balances").fetchone()
            if row is not None and int(row["count"]) == 0:
                self._seed_locked(seed)
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def reset(self, *, seed: int = 20260807) -> None:
        with self._lock:
            for table in ("trades", "equity_snapshots", "opportunities", "balances"):
                self._connection.execute(f"DELETE FROM {table}")
            self._seed_locked(seed)
            self._connection.commit()

    def _seed_locked(self, seed: int) -> None:
        rng = random.Random(seed)
        balances = {
            "bitbank": {"JPY": 1_500_000.0, "BTC": 0.025},
            "gmocoin": {"JPY": 1_500_000.0, "BTC": 0.025},
            "bitflyer": {"JPY": 1_000_000.0, "BTC": 0.020},
            "coincheck": {"JPY": 1_000_000.0, "BTC": 0.020},
        }
        reference_price = 11_000_000.0
        previous_equity = self._equity_from_mapping(balances, reference_price)
        peak_equity = previous_equity
        now = datetime.now(UTC).replace(microsecond=0)

        for days_ago in range(44, -1, -1):
            ts = now - timedelta(days=days_ago)
            reference_price *= 1.0 + rng.gauss(0.0004, 0.011)
            for trade_number in range(rng.randint(1, 4)):
                buy_exchange, sell_exchange = rng.sample(EXCHANGE_IDS, 2)
                gross_bps = rng.uniform(12.0, 46.0)
                half_spread = gross_bps / 20_000.0
                buy_price = reference_price * (1.0 - half_spread)
                sell_price = reference_price * (1.0 + half_spread)
                quantity = rng.uniform(0.0008, 0.0035)
                max_buy = max(0.0, balances[buy_exchange]["JPY"] - 100_000.0)
                max_sell = max(0.0, balances[sell_exchange]["BTC"] - 0.002)
                quantity = min(quantity, max_buy / buy_price, max_sell)
                status = rng.choices(
                    ["filled", "partial", "rejected"],
                    weights=[82, 12, 6],
                    k=1,
                )[0]
                if status == "partial":
                    quantity *= 0.5
                slippage_bps = rng.uniform(0.7, 8.0)
                buy_fill = buy_price * (1.0 + slippage_bps / 20_000.0)
                sell_fill = sell_price * (1.0 - slippage_bps / 20_000.0)
                buy_fee = buy_fill * quantity * DEFAULT_FEE_RATES[buy_exchange]
                sell_fee = sell_fill * quantity * DEFAULT_FEE_RATES[sell_exchange]
                fees = buy_fee + sell_fee
                pnl = sell_fill * quantity - buy_fill * quantity - fees
                if status == "rejected" or quantity <= 0.0:
                    quantity = max(quantity, 0.0)
                    pnl = 0.0
                    fees = 0.0
                else:
                    balances[buy_exchange]["JPY"] -= buy_fill * quantity + buy_fee
                    balances[buy_exchange]["BTC"] += quantity
                    balances[sell_exchange]["BTC"] -= quantity
                    balances[sell_exchange]["JPY"] += sell_fill * quantity - sell_fee

                notional = max(buy_fill * quantity, 1.0)
                net_bps = pnl / notional * 10_000.0
                trade_ts = ts + timedelta(minutes=trade_number * 13)
                self._insert_trade_locked(
                    trade_id=f"seed-{days_ago}-{trade_number}-{uuid4().hex[:8]}",
                    ts=trade_ts,
                    buy_exchange=buy_exchange,
                    sell_exchange=sell_exchange,
                    quantity=quantity,
                    buy_price=buy_fill,
                    sell_price=sell_fill,
                    gross_bps=gross_bps,
                    net_bps=net_bps,
                    fees_jpy=fees,
                    slippage_bps=slippage_bps,
                    latency_ms=rng.uniform(65.0, 390.0),
                    pnl_jpy=pnl,
                    status=status,
                    source="synthetic-research-baseline",
                )
                self._connection.execute(
                    """
                    INSERT INTO opportunities (
                        ts, buy_exchange, sell_exchange, buy_ask, sell_bid,
                        net_bps, executable_notional_jpy, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade_ts.isoformat(),
                        buy_exchange,
                        sell_exchange,
                        buy_price,
                        sell_price,
                        net_bps,
                        min(notional, 100_000.0),
                        "synthetic-research-baseline",
                    ),
                )

            equity = self._equity_from_mapping(balances, reference_price)
            peak_equity = max(peak_equity, equity)
            drawdown = (equity / peak_equity - 1.0) * 100.0
            self._connection.execute(
                """
                INSERT INTO equity_snapshots (
                    ts, equity_jpy, period_pnl_jpy, drawdown_pct,
                    reference_price_jpy, source
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    ts.isoformat(),
                    equity,
                    equity - previous_equity,
                    drawdown,
                    reference_price,
                    "synthetic-research-baseline",
                ),
            )
            previous_equity = equity

        for exchange, assets in balances.items():
            for asset, amount in assets.items():
                self._connection.execute(
                    "INSERT INTO balances (exchange, asset, amount) VALUES (?, ?, ?)",
                    (exchange, asset, amount),
                )

    @staticmethod
    def _equity_from_mapping(
        balances: dict[str, dict[str, float]], reference_price: float
    ) -> float:
        total_jpy = sum(item["JPY"] for item in balances.values())
        total_btc = sum(item["BTC"] for item in balances.values())
        return total_jpy + total_btc * reference_price

    def _insert_trade_locked(
        self,
        *,
        trade_id: str,
        ts: datetime,
        buy_exchange: str,
        sell_exchange: str,
        quantity: float,
        buy_price: float,
        sell_price: float,
        gross_bps: float,
        net_bps: float,
        fees_jpy: float,
        slippage_bps: float,
        latency_ms: float,
        pnl_jpy: float,
        status: str,
        source: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO trades (
                id, ts, market, buy_exchange, sell_exchange, quantity,
                buy_price, sell_price, gross_bps, net_bps, fees_jpy,
                slippage_bps, latency_ms, pnl_jpy, status, source
            ) VALUES (?, ?, 'BTC/JPY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                ts.isoformat(),
                buy_exchange,
                sell_exchange,
                quantity,
                buy_price,
                sell_price,
                gross_bps,
                net_bps,
                fees_jpy,
                slippage_bps,
                latency_ms,
                pnl_jpy,
                status,
                source,
            ),
        )

    def last_reference_price(self) -> float:
        with self._lock:
            row = self._connection.execute(
                """
                SELECT reference_price_jpy
                FROM equity_snapshots
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
            return float(row["reference_price_jpy"]) if row is not None else 11_000_000.0

    def _database_equity_locked(self, reference_price: float) -> float:
        rows = self._connection.execute(
            "SELECT asset, SUM(amount) AS amount FROM balances GROUP BY asset"
        ).fetchall()
        by_asset = {str(row["asset"]): float(row["amount"]) for row in rows}
        return by_asset.get("JPY", 0.0) + by_asset.get("BTC", 0.0) * reference_price

    def _record_snapshot_locked(self, reference_price: float, source: str) -> None:
        equity = self._database_equity_locked(reference_price)
        latest = self._connection.execute(
            "SELECT equity_jpy FROM equity_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        previous = float(latest["equity_jpy"]) if latest is not None else equity
        peak_row = self._connection.execute(
            "SELECT MAX(equity_jpy) AS peak FROM equity_snapshots"
        ).fetchone()
        historical_peak = float(peak_row["peak"] or equity) if peak_row is not None else equity
        peak = max(historical_peak, equity)
        drawdown = (equity / peak - 1.0) * 100.0 if peak > 0.0 else 0.0
        self._connection.execute(
            """
            INSERT INTO equity_snapshots (
                ts, equity_jpy, period_pnl_jpy, drawdown_pct,
                reference_price_jpy, source
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(UTC).isoformat(),
                equity,
                equity - previous,
                drawdown,
                reference_price,
                source,
            ),
        )
        self._connection.execute(
            """
            DELETE FROM equity_snapshots
            WHERE id NOT IN (
                SELECT id FROM equity_snapshots ORDER BY id DESC LIMIT 5000
            )
            """
        )

    def record_mark(self, reference_price: float, source: str) -> None:
        with self._lock:
            self._record_snapshot_locked(reference_price, source)
            self._connection.commit()

    def record_opportunities(
        self,
        opportunities: list[Opportunity],
        *,
        source: str,
        max_notional_jpy: float,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self._lock:
            for item in opportunities[:20]:
                notional = min(max_notional_jpy, float(item.top_size * item.buy_ask))
                self._connection.execute(
                    """
                    INSERT INTO opportunities (
                        ts, buy_exchange, sell_exchange, buy_ask, sell_bid,
                        net_bps, executable_notional_jpy, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now,
                        item.buy_exchange,
                        item.sell_exchange,
                        float(item.buy_ask),
                        float(item.sell_bid),
                        float(item.net_spread_bps),
                        notional,
                        source,
                    ),
                )
            self._connection.execute(
                """
                DELETE FROM opportunities
                WHERE id NOT IN (
                    SELECT id FROM opportunities ORDER BY id DESC LIMIT 1000
                )
                """
            )
            self._connection.commit()

    def execute_paper_trade(
        self,
        opportunity: Opportunity,
        *,
        fee_rates: dict[str, float],
        risk: RiskLimits,
        source: str,
        rng: random.Random,
    ) -> dict[str, Any] | None:
        with self._lock:
            rows = self._connection.execute(
                "SELECT exchange, asset, amount FROM balances"
            ).fetchall()
            balances: dict[str, dict[str, float]] = defaultdict(dict)
            for row in rows:
                balances[str(row["exchange"])][str(row["asset"])] = float(row["amount"])

            buy_exchange = opportunity.buy_exchange
            sell_exchange = opportunity.sell_exchange
            buy_price = float(opportunity.buy_ask)
            sell_price = float(opportunity.sell_bid)
            buy_jpy = balances[buy_exchange].get("JPY", 0.0)
            sell_btc = balances[sell_exchange].get("BTC", 0.0)
            max_by_jpy = max(0.0, buy_jpy - risk.min_jpy_reserve) / buy_price
            max_by_btc = max(0.0, sell_btc - risk.min_btc_reserve)
            quantity = min(
                float(opportunity.top_size),
                risk.max_notional_jpy / buy_price,
                max_by_jpy,
                max_by_btc,
            )
            if quantity <= 0.0:
                return None

            leg_slippage = rng.uniform(0.25, max(0.25, risk.max_slippage_bps))
            buy_fill = buy_price * (1.0 + leg_slippage / 10_000.0)
            sell_fill = sell_price * (1.0 - leg_slippage / 10_000.0)
            buy_fee = buy_fill * quantity * fee_rates.get(buy_exchange, 0.0)
            sell_fee = sell_fill * quantity * fee_rates.get(sell_exchange, 0.0)
            fees = buy_fee + sell_fee
            pnl = sell_fill * quantity - buy_fill * quantity - fees
            notional = buy_fill * quantity
            net_bps = pnl / notional * 10_000.0 if notional > 0.0 else 0.0

            self._connection.execute(
                "UPDATE balances SET amount = amount - ? WHERE exchange = ? AND asset = 'JPY'",
                (buy_fill * quantity + buy_fee, buy_exchange),
            )
            self._connection.execute(
                "UPDATE balances SET amount = amount + ? WHERE exchange = ? AND asset = 'BTC'",
                (quantity, buy_exchange),
            )
            self._connection.execute(
                "UPDATE balances SET amount = amount - ? WHERE exchange = ? AND asset = 'BTC'",
                (quantity, sell_exchange),
            )
            self._connection.execute(
                "UPDATE balances SET amount = amount + ? WHERE exchange = ? AND asset = 'JPY'",
                (sell_fill * quantity - sell_fee, sell_exchange),
            )

            trade_id = f"paper-{uuid4().hex}"
            timestamp = datetime.now(UTC)
            self._insert_trade_locked(
                trade_id=trade_id,
                ts=timestamp,
                buy_exchange=buy_exchange,
                sell_exchange=sell_exchange,
                quantity=quantity,
                buy_price=buy_fill,
                sell_price=sell_fill,
                gross_bps=float(opportunity.gross_spread_bps),
                net_bps=net_bps,
                fees_jpy=fees,
                slippage_bps=leg_slippage * 2.0,
                latency_ms=rng.uniform(45.0, 280.0),
                pnl_jpy=pnl,
                status="filled",
                source=source,
            )
            self._record_snapshot_locked((buy_fill + sell_fill) / 2.0, source)
            self._connection.commit()
            return {
                "id": trade_id,
                "ts": timestamp.isoformat(),
                "pnl_jpy": pnl,
                "net_bps": net_bps,
                "quantity": quantity,
            }

    def today_realized_pnl(self) -> float:
        today = datetime.now(UTC).date().isoformat()
        with self._lock:
            row = self._connection.execute(
                """
                SELECT COALESCE(SUM(pnl_jpy), 0) AS pnl
                FROM trades
                WHERE substr(ts, 1, 10) = ? AND status IN ('filled', 'partial')
                """,
                (today,),
            ).fetchone()
            return float(row["pnl"]) if row is not None else 0.0

    def daily_series(self, *, limit: int = 120) -> list[dict[str, float | str]]:
        with self._lock:
            snapshots = self._connection.execute(
                "SELECT ts, equity_jpy, reference_price_jpy, source FROM equity_snapshots ORDER BY ts"
            ).fetchall()
            trade_rows = self._connection.execute(
                """
                SELECT substr(ts, 1, 10) AS day, COALESCE(SUM(pnl_jpy), 0) AS pnl
                FROM trades
                WHERE status IN ('filled', 'partial')
                GROUP BY substr(ts, 1, 10)
                """
            ).fetchall()

        strategy_pnl = {str(row["day"]): float(row["pnl"]) for row in trade_rows}
        closing: dict[str, sqlite3.Row] = {}
        for row in snapshots:
            closing[str(row["ts"])[:10]] = row

        result: list[dict[str, float | str]] = []
        previous: float | None = None
        peak = 0.0
        for day in sorted(closing):
            row = closing[day]
            equity = float(row["equity_jpy"])
            peak = max(peak, equity)
            daily_pnl = 0.0 if previous is None else equity - previous
            daily_return = 0.0 if previous in {None, 0.0} else daily_pnl / previous * 100.0
            drawdown = (equity / peak - 1.0) * 100.0 if peak > 0.0 else 0.0
            result.append(
                {
                    "date": day,
                    "equity_jpy": equity,
                    "daily_pnl_jpy": daily_pnl,
                    "strategy_pnl_jpy": strategy_pnl.get(day, 0.0),
                    "return_pct": daily_return,
                    "drawdown_pct": drawdown,
                    "reference_price_jpy": float(row["reference_price_jpy"]),
                    "source": str(row["source"]),
                }
            )
            previous = equity
        return result[-limit:]

    def metrics(self) -> dict[str, float | int | None]:
        daily = self.daily_series(limit=1000)
        if not daily:
            return {}
        start_equity = float(daily[0]["equity_jpy"])
        end_equity = float(daily[-1]["equity_jpy"])
        returns = [float(item["return_pct"]) / 100.0 for item in daily[1:]]
        mean_return = statistics.fmean(returns) if returns else 0.0
        volatility = statistics.stdev(returns) if len(returns) > 1 else 0.0
        annualized_volatility = volatility * math.sqrt(365.0)
        sharpe = mean_return / volatility * math.sqrt(365.0) if volatility > 0.0 else 0.0
        downside = [min(value, 0.0) for value in returns]
        downside_deviation = math.sqrt(statistics.fmean(value * value for value in downside))
        sortino = (
            mean_return / downside_deviation * math.sqrt(365.0) if downside_deviation > 0.0 else 0.0
        )
        total_return = end_equity / start_equity - 1.0 if start_equity > 0.0 else 0.0
        periods = max(len(returns), 1)
        annualized_return = (1.0 + total_return) ** (365.0 / periods) - 1.0
        max_drawdown = min(float(item["drawdown_pct"]) for item in daily)
        calmar = annualized_return * 100.0 / abs(max_drawdown) if max_drawdown < 0.0 else 0.0

        with self._lock:
            rows = self._connection.execute(
                "SELECT pnl_jpy, fees_jpy, net_bps, latency_ms, status, quantity, buy_price FROM trades"
            ).fetchall()
        attempted = len(rows)
        executed = [row for row in rows if row["status"] in {"filled", "partial"}]
        wins = [float(row["pnl_jpy"]) for row in executed if float(row["pnl_jpy"]) > 0.0]
        losses = [float(row["pnl_jpy"]) for row in executed if float(row["pnl_jpy"]) < 0.0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0.0 else None
        realized_pnl = sum(float(row["pnl_jpy"]) for row in executed)
        fees = sum(float(row["fees_jpy"]) for row in executed)
        turnover = sum(float(row["quantity"]) * float(row["buy_price"]) for row in executed)
        avg_net_bps = (
            statistics.fmean(float(row["net_bps"]) for row in executed) if executed else 0.0
        )
        avg_latency = (
            statistics.fmean(float(row["latency_ms"]) for row in executed) if executed else 0.0
        )
        win_rate = len(wins) / len(executed) * 100.0 if executed else 0.0
        fill_ratio = len(executed) / attempted * 100.0 if attempted else 0.0
        latest_daily = daily[-1]
        return {
            "equity_jpy": end_equity,
            "daily_change_jpy": float(latest_daily["daily_pnl_jpy"]),
            "realized_pnl_jpy": realized_pnl,
            "today_realized_pnl_jpy": self.today_realized_pnl(),
            "total_return_pct": total_return * 100.0,
            "annualized_return_pct": annualized_return * 100.0,
            "annualized_volatility_pct": annualized_volatility * 100.0,
            "max_drawdown_pct": max_drawdown,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "win_rate_pct": win_rate,
            "profit_factor": profit_factor,
            "fill_ratio_pct": fill_ratio,
            "fees_jpy": fees,
            "turnover_jpy": turnover,
            "avg_net_bps": avg_net_bps,
            "avg_latency_ms": avg_latency,
            "trade_count": len(executed),
            "attempt_count": attempted,
        }

    def balance_summary(self) -> dict[str, Any]:
        reference_price = self.last_reference_price()
        with self._lock:
            rows = self._connection.execute(
                "SELECT exchange, asset, amount FROM balances ORDER BY exchange, asset"
            ).fetchall()
        balances: dict[str, dict[str, float]] = defaultdict(dict)
        for row in rows:
            balances[str(row["exchange"])][str(row["asset"])] = float(row["amount"])
        items: list[dict[str, float | str]] = []
        grand_total = 0.0
        for exchange in EXCHANGE_IDS:
            jpy = balances[exchange].get("JPY", 0.0)
            btc = balances[exchange].get("BTC", 0.0)
            total = jpy + btc * reference_price
            grand_total += total
            items.append(
                {
                    "exchange": exchange,
                    "jpy": jpy,
                    "btc": btc,
                    "btc_value_jpy": btc * reference_price,
                    "total_jpy": total,
                }
            )
        for item in items:
            total = float(item["total_jpy"])
            item["share_pct"] = total / grand_total * 100.0 if grand_total > 0.0 else 0.0
        return {
            "items": items,
            "reference_price_jpy": reference_price,
            "total_equity_jpy": grand_total,
            "asset_totals": {
                "JPY": sum(float(item["jpy"]) for item in items),
                "BTC": sum(float(item["btc"]) for item in items),
            },
        }

    def trades(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM trades ORDER BY ts DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def opportunities(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM opportunities ORDER BY ts DESC, net_bps DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def overview(self, *, status: dict[str, Any], risk: RiskLimits) -> dict[str, Any]:
        daily = self.daily_series(limit=120)
        return {
            "generated_at": datetime.now(UTC).isoformat(),
            "status": status,
            "risk": asdict(risk),
            "metrics": self.metrics(),
            "equity": daily,
            "daily": daily[-45:],
            "balances": self.balance_summary(),
            "trades": self.trades(limit=120),
            "opportunities": self.opportunities(limit=60),
            "data_disclosure": {
                "seeded_history": True,
                "seed_label": "synthetic-research-baseline",
                "real_order_submission": False,
                "private_api_called": False,
            },
        }


class SimulationEngine:
    def __init__(
        self,
        store: SimulationStore,
        *,
        config_path: str | Path = "config.yml",
        interval_seconds: float = 30.0,
        mode: str = "public-live-paper",
        seed: int = 20260807,
    ) -> None:
        self.store = store
        self.config_path = Path(config_path)
        self.interval_seconds = max(5.0, float(interval_seconds))
        self.mode = mode if mode in VALID_MODES else "public-live-paper"
        self.risk = RiskLimits()
        self.seed = seed
        self._rng = random.Random(seed + 1)
        self._task: asyncio.Task[None] | None = None
        self._run_lock = asyncio.Lock()
        self.running = False
        self.kill_switch = False
        self.last_scan_at: str | None = None
        self.last_source = "synthetic-research-baseline"
        self.last_errors: dict[str, str] = {}
        self.last_trade: dict[str, Any] | None = None

    def initialize(self) -> None:
        self.store.initialize(seed=self.seed)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            self.running = True
            return
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="arb-paper-loop")

    async def stop(self) -> None:
        self.running = False
        if self._task is None:
            return
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def close(self) -> None:
        await self.stop()
        self.store.close()

    async def _loop(self) -> None:
        while self.running:
            await self.run_once()
            await asyncio.sleep(self.interval_seconds)

    def _can_execute(self) -> bool:
        if self.kill_switch:
            return False
        return self.store.today_realized_pnl() > -self.risk.max_daily_loss_jpy

    async def run_once(self) -> dict[str, Any]:
        async with self._run_lock:
            if self.mode == "synthetic-replay":
                result = await self._run_synthetic(source="synthetic-replay")
            else:
                result = await self._run_public_live()
            self.last_scan_at = datetime.now(UTC).isoformat()
            return result

    async def _run_public_live(self) -> dict[str, Any]:
        try:
            config = load_config(self.config_path)
            books, errors = await fetch_orderbooks(config)
            self.last_errors = errors
            if not books:
                return await self._run_synthetic(source="synthetic-fallback")
            opportunities = calculate_opportunities(
                books,
                config.exchanges,
                min_net_bps=Decimal(str(self.risk.min_net_bps)),
            )
            mids: list[float] = []
            for book in books:
                if book.best_bid is not None and book.best_ask is not None:
                    mids.append((float(book.best_bid.price) + float(book.best_ask.price)) / 2.0)
            reference_price = statistics.fmean(mids) if mids else self.store.last_reference_price()
            source = "public-live-paper"
            self.store.record_opportunities(
                opportunities,
                source=source,
                max_notional_jpy=self.risk.max_notional_jpy,
            )
            fee_rates = {item.name: float(item.taker_fee_rate) for item in config.exchanges}
            trade = None
            if opportunities and self._can_execute():
                trade = self.store.execute_paper_trade(
                    opportunities[0],
                    fee_rates=fee_rates,
                    risk=self.risk,
                    source=source,
                    rng=self._rng,
                )
            if trade is None:
                self.store.record_mark(reference_price, source)
            self.last_trade = trade
            self.last_source = source
            return {
                "source": source,
                "books": len(books),
                "opportunities": len(opportunities),
                "trade": trade,
                "errors": errors,
            }
        except (FileNotFoundError, ValueError, OSError) as exc:
            self.last_errors = {"configuration": str(exc)}
            return await self._run_synthetic(source="synthetic-fallback")

    async def _run_synthetic(self, *, source: str) -> dict[str, Any]:
        reference_price = self.store.last_reference_price()
        reference_price *= 1.0 + self._rng.gauss(0.0, 0.0007)
        buy_exchange, sell_exchange = self._rng.sample(EXCHANGE_IDS, 2)
        gross_bps = self._rng.uniform(15.0, 45.0)
        half_spread = gross_bps / 20_000.0
        buy_price = reference_price * (1.0 - half_spread)
        sell_price = reference_price * (1.0 + half_spread)
        assumed_fees = (
            DEFAULT_FEE_RATES[buy_exchange] + DEFAULT_FEE_RATES[sell_exchange]
        ) * 10_000.0
        net_bps = gross_bps - assumed_fees - 2.5
        top_size = 0.01
        opportunity = Opportunity(
            market="BTC/JPY",
            buy_exchange=buy_exchange,
            sell_exchange=sell_exchange,
            buy_ask=Decimal(str(buy_price)),
            sell_bid=Decimal(str(sell_price)),
            top_size=Decimal(str(top_size)),
            gross_spread_bps=Decimal(str(gross_bps)),
            net_spread_bps=Decimal(str(net_bps)),
            net_profit_quote=Decimal(str((sell_price - buy_price) * top_size)),
        )
        opportunities = [opportunity]
        self.store.record_opportunities(
            opportunities,
            source=source,
            max_notional_jpy=self.risk.max_notional_jpy,
        )
        trade = None
        if net_bps >= self.risk.min_net_bps and self._can_execute():
            trade = self.store.execute_paper_trade(
                opportunity,
                fee_rates=DEFAULT_FEE_RATES,
                risk=self.risk,
                source=source,
                rng=self._rng,
            )
        if trade is None:
            self.store.record_mark(reference_price, source)
        self.last_trade = trade
        self.last_source = source
        return {
            "source": source,
            "books": 0,
            "opportunities": 1,
            "trade": trade,
            "errors": self.last_errors,
        }

    def set_risk(self, **updates: float) -> RiskLimits:
        self.risk = replace(self.risk, **updates)
        return self.risk

    def set_mode(self, mode: str) -> str:
        if mode not in VALID_MODES:
            raise ValueError(f"unsupported mode: {mode}")
        self.mode = mode
        return self.mode

    def set_kill_switch(self, enabled: bool) -> bool:
        self.kill_switch = bool(enabled)
        return self.kill_switch

    def reset(self, *, seed: int | None = None) -> None:
        selected_seed = self.seed if seed is None else int(seed)
        self.seed = selected_seed
        self._rng = random.Random(selected_seed + 1)
        self.store.reset(seed=selected_seed)
        self.last_trade = None
        self.last_errors = {}
        self.last_source = "synthetic-research-baseline"

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "mode": self.mode,
            "kill_switch": self.kill_switch,
            "last_scan_at": self.last_scan_at,
            "last_source": self.last_source,
            "last_errors": self.last_errors,
            "last_trade": self.last_trade,
            "interval_seconds": self.interval_seconds,
            "real_order_submission": False,
            "private_api_called": False,
            "execution_label": "PAPER ONLY",
        }

    def overview(self) -> dict[str, Any]:
        return self.store.overview(status=self.status(), risk=self.risk)
