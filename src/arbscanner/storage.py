from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class PaperStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS balances (
                    exchange TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    amount REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (exchange, asset)
                );

                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    executed_at TEXT NOT NULL,
                    market TEXT NOT NULL,
                    buy_exchange TEXT NOT NULL,
                    sell_exchange TEXT NOT NULL,
                    quantity_btc REAL NOT NULL,
                    buy_price_jpy REAL NOT NULL,
                    sell_price_jpy REAL NOT NULL,
                    gross_pnl_jpy REAL NOT NULL,
                    fees_jpy REAL NOT NULL,
                    slippage_jpy REAL NOT NULL,
                    rebalance_reserve_jpy REAL NOT NULL,
                    net_pnl_jpy REAL NOT NULL,
                    net_spread_bps REAL NOT NULL,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    equity_jpy REAL NOT NULL,
                    cash_jpy REAL NOT NULL,
                    crypto_jpy REAL NOT NULL,
                    reference_price_jpy REAL NOT NULL,
                    daily_pnl_jpy REAL NOT NULL,
                    data_source TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
        self.seed_demo_if_empty()

    def seed_demo_if_empty(self) -> None:
        with self._connect() as connection:
            count = connection.execute("SELECT COUNT(*) AS count FROM equity_snapshots").fetchone()
            if count is not None and int(count["count"]) > 0:
                return

            now = datetime.now(UTC).replace(microsecond=0)
            start = now - timedelta(days=30)
            reference_price = 10_200_000.0
            initial_cash = 1_600_000.0
            initial_btc = 0.08
            initial_equity = initial_cash + initial_btc * reference_price
            daily_pnls = [
                850,
                -420,
                1120,
                640,
                -980,
                1340,
                720,
                -310,
                1560,
                -760,
                480,
                910,
                -1250,
                1720,
                530,
                -290,
                1180,
                760,
                -640,
                1490,
                350,
                -870,
                980,
                610,
                -430,
                1270,
                440,
                -520,
                1050,
                690,
            ]
            cumulative = 0.0
            connection.execute(
                """
                INSERT INTO equity_snapshots (
                    recorded_at, equity_jpy, cash_jpy, crypto_jpy,
                    reference_price_jpy, daily_pnl_jpy, data_source
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    start.isoformat(),
                    initial_equity,
                    initial_cash,
                    initial_btc * reference_price,
                    reference_price,
                    0.0,
                    "seeded_research_demo",
                ),
            )

            venues = ("bitbank", "gmocoin", "bitflyer", "coincheck")
            for index, net_pnl in enumerate(daily_pnls, start=1):
                cumulative += net_pnl
                timestamp = start + timedelta(days=index)
                cash = initial_cash + cumulative
                equity = cash + initial_btc * reference_price
                connection.execute(
                    """
                    INSERT INTO equity_snapshots (
                        recorded_at, equity_jpy, cash_jpy, crypto_jpy,
                        reference_price_jpy, daily_pnl_jpy, data_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp.isoformat(),
                        equity,
                        cash,
                        initial_btc * reference_price,
                        reference_price,
                        float(net_pnl),
                        "seeded_research_demo",
                    ),
                )

                quantity = 0.0035 + (index % 5) * 0.0005
                buy_price = reference_price * (0.999 + (index % 4) * 0.0002)
                estimated_notional = quantity * buy_price
                fees = estimated_notional * 0.0010
                slippage = estimated_notional * 0.0002
                reserve = estimated_notional * 0.0003
                gross_pnl = net_pnl + fees + slippage + reserve
                sell_price = buy_price + gross_pnl / quantity
                buy_exchange = venues[index % len(venues)]
                sell_exchange = venues[(index + 1) % len(venues)]
                connection.execute(
                    """
                    INSERT INTO trades (
                        executed_at, market, buy_exchange, sell_exchange,
                        quantity_btc, buy_price_jpy, sell_price_jpy,
                        gross_pnl_jpy, fees_jpy, slippage_jpy,
                        rebalance_reserve_jpy, net_pnl_jpy, net_spread_bps,
                        status, source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        timestamp.isoformat(),
                        "BTC/JPY",
                        buy_exchange,
                        sell_exchange,
                        quantity,
                        buy_price,
                        sell_price,
                        gross_pnl,
                        fees,
                        slippage,
                        reserve,
                        float(net_pnl),
                        float(net_pnl / estimated_notional * 10_000),
                        "simulated_filled",
                        "seeded_research_demo",
                    ),
                )

            per_venue_pnl = cumulative / len(venues)
            for venue in venues:
                connection.execute(
                    """
                    INSERT INTO balances (exchange, asset, amount, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (venue, "JPY", 400_000.0 + per_venue_pnl, now.isoformat()),
                )
                connection.execute(
                    """
                    INSERT INTO balances (exchange, asset, amount, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (venue, "BTC", 0.02, now.isoformat()),
                )

            connection.execute(
                """
                INSERT INTO events (created_at, level, kind, message, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    now.isoformat(),
                    "info",
                    "demo_seeded",
                    "30日分の明示的なシミュレーション履歴を初期化しました。",
                    json.dumps(
                        {
                            "reference_price_jpy": reference_price,
                            "initial_equity_jpy": initial_equity,
                            "source": "seeded_research_demo",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            connection.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                ("risk.kill_switch", "false", now.isoformat()),
            )

    def list_balances(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT exchange, asset, amount, updated_at FROM balances ORDER BY exchange, asset"
            ).fetchall()
        return [dict(row) for row in rows]

    def balance_map(self) -> dict[tuple[str, str], float]:
        return {
            (str(row["exchange"]), str(row["asset"])): float(row["amount"])
            for row in self.list_balances()
        }

    def list_trades(self, limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 1000))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trades ORDER BY executed_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_equity(self, limit: int = 2000) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 10_000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM (
                    SELECT * FROM equity_snapshots
                    ORDER BY recorded_at DESC, id DESC LIMIT ?
                ) ORDER BY recorded_at ASC, id ASC
                """,
                (safe_limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_equity(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM equity_snapshots ORDER BY recorded_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row is not None else None

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 1000))
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events ORDER BY created_at DESC, id DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            details = item.pop("details_json", None)
            item["details"] = json.loads(details) if details else None
            result.append(item)
        return result

    def record_event(
        self,
        *,
        level: str,
        kind: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events (created_at, level, kind, message, details_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    now,
                    level,
                    kind,
                    message,
                    json.dumps(details, ensure_ascii=False) if details else None,
                ),
            )
            connection.execute(
                """
                DELETE FROM events WHERE id NOT IN (
                    SELECT id FROM events ORDER BY created_at DESC, id DESC LIMIT 1000
                )
                """
            )

    def record_equity(self, snapshot: dict[str, Any]) -> None:
        with self._connect() as connection:
            self._insert_equity(connection, snapshot)

    def record_trade_and_state(
        self,
        *,
        trade: dict[str, Any],
        balance_updates: dict[tuple[str, str], float],
        equity: dict[str, Any],
    ) -> None:
        now = str(trade["executed_at"])
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO trades (
                    executed_at, market, buy_exchange, sell_exchange,
                    quantity_btc, buy_price_jpy, sell_price_jpy,
                    gross_pnl_jpy, fees_jpy, slippage_jpy,
                    rebalance_reserve_jpy, net_pnl_jpy, net_spread_bps,
                    status, source
                ) VALUES (
                    :executed_at, :market, :buy_exchange, :sell_exchange,
                    :quantity_btc, :buy_price_jpy, :sell_price_jpy,
                    :gross_pnl_jpy, :fees_jpy, :slippage_jpy,
                    :rebalance_reserve_jpy, :net_pnl_jpy, :net_spread_bps,
                    :status, :source
                )
                """,
                trade,
            )
            for (exchange, asset), amount in balance_updates.items():
                connection.execute(
                    """
                    INSERT INTO balances (exchange, asset, amount, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(exchange, asset) DO UPDATE SET
                        amount = excluded.amount,
                        updated_at = excluded.updated_at
                    """,
                    (exchange, asset, amount, now),
                )
            self._insert_equity(connection, equity)

    def _insert_equity(self, connection: sqlite3.Connection, snapshot: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO equity_snapshots (
                recorded_at, equity_jpy, cash_jpy, crypto_jpy,
                reference_price_jpy, daily_pnl_jpy, data_source
            ) VALUES (
                :recorded_at, :equity_jpy, :cash_jpy, :crypto_jpy,
                :reference_price_jpy, :daily_pnl_jpy, :data_source
            )
            """,
            snapshot,
        )

    def get_setting(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row is not None else None

    def set_setting(self, key: str, value: str) -> None:
        now = datetime.now(UTC).replace(microsecond=0).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, value, now),
            )
