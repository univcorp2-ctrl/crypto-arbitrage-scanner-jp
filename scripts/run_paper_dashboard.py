from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from arbscanner.config import ScannerConfig, load_config
from arbscanner.models import Opportunity, OrderBook
from arbscanner.paper_ledger import (
    BTC_QUANTUM,
    PaperRiskConfig,
    calculate_metrics,
    execute_opportunity,
    initialize_balances,
    median_reference_price,
    portfolio_equity,
)
from arbscanner.scanner import calculate_opportunities, fetch_orderbooks

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "paper_state.json"
DASHBOARD_PATH = ROOT / "docs" / "data" / "dashboard.json"
PAPER_CONFIG_PATH = ROOT / "paper.example.yml"
SCANNER_CONFIG_PATH = ROOT / "config.yml"
JST = ZoneInfo("Asia/Tokyo")

CONNECTORS = [
    {
        "id": "bitbank",
        "name": "bitbank",
        "priority": 1,
        "priority_reason": "JPY板・Private RESTの仕様が明確で、最初の接続検証に向く",
        "public_status": "connected",
        "private_status": "not_configured",
        "api_key_env": "BITBANK_API_KEY",
        "api_secret_env": "BITBANK_API_SECRET",
        "auth_headers": "ACCESS-KEY / ACCESS-REQUEST-TIME / ACCESS-SIGNATURE",
        "recommended_permissions": ["資産参照", "注文参照", "約定履歴参照"],
        "production_permission": "現物注文（本番解放時のみ）",
        "forbidden_permissions": ["出金", "送付"],
        "ip_restriction": "推奨",
        "fee_assumption_bps": 10,
        "docs_url": "https://github.com/bitbankinc/bitbank-api-docs/blob/master/rest-api.md",
        "secret_location": "GitHub Actions Secrets または非公開バックエンドのSecret",
    },
    {
        "id": "gmocoin",
        "name": "GMOコイン",
        "priority": 2,
        "priority_reason": "現物Taker手数料の仮定が低く、REST/WebSocketが整理されている",
        "public_status": "connected",
        "private_status": "not_configured",
        "api_key_env": "GMO_COIN_API_KEY",
        "api_secret_env": "GMO_COIN_API_SECRET",
        "auth_headers": "API-KEY / API-TIMESTAMP / API-SIGN",
        "recommended_permissions": ["資産参照", "注文参照", "約定履歴参照"],
        "production_permission": "現物注文（本番解放時のみ）",
        "forbidden_permissions": ["出金", "振替"],
        "ip_restriction": "推奨",
        "fee_assumption_bps": 5,
        "docs_url": "https://api.coin.z.com/docs/",
        "secret_location": "GitHub Actions Secrets または非公開バックエンドのSecret",
    },
    {
        "id": "bitflyer",
        "name": "bitFlyer Lightning",
        "priority": 3,
        "priority_reason": "国内主要板として有用。取引量別手数料を口座実績に合わせて補正する",
        "public_status": "connected",
        "private_status": "not_configured",
        "api_key_env": "BITFLYER_API_KEY",
        "api_secret_env": "BITFLYER_API_SECRET",
        "auth_headers": "ACCESS-KEY / ACCESS-TIMESTAMP / ACCESS-SIGN",
        "recommended_permissions": ["資産参照", "注文参照", "約定履歴参照"],
        "production_permission": "Trade（本番解放時のみ）",
        "forbidden_permissions": ["Withdraw"],
        "ip_restriction": "可能なら設定",
        "fee_assumption_bps": 15,
        "docs_url": "https://lightning.bitflyer.com/docs",
        "secret_location": "GitHub Actions Secrets または非公開バックエンドのSecret",
    },
    {
        "id": "coincheck",
        "name": "Coincheck Exchange",
        "priority": 4,
        "priority_reason": "取引所APIとPrivate WebSocketを備える。板・注文条件を個別検証する",
        "public_status": "connected",
        "private_status": "not_configured",
        "api_key_env": "COINCHECK_API_KEY",
        "api_secret_env": "COINCHECK_API_SECRET",
        "auth_headers": "ACCESS-KEY / ACCESS-NONCE / ACCESS-SIGNATURE",
        "recommended_permissions": ["残高参照", "注文参照", "取引履歴参照"],
        "production_permission": "注文作成・取消（本番解放時のみ）",
        "forbidden_permissions": ["暗号資産送付", "日本円出金"],
        "ip_restriction": "推奨",
        "fee_assumption_bps": 0,
        "docs_url": "https://coincheck.com/documents/exchange/api",
        "secret_location": "GitHub Actions Secrets または非公開バックエンドのSecret",
    },
]


def _decimal(value: Any, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


def _load_paper_settings() -> dict[str, Any]:
    with PAPER_CONFIG_PATH.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ValueError("paper config root must be a mapping")
    return raw


def _load_state() -> dict[str, Any] | None:
    if not STATE_PATH.exists():
        return None
    with STATE_PATH.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("paper state root must be an object")
    return loaded


def _decode_balances(state: dict[str, Any]) -> dict[str, dict[str, Decimal]]:
    raw = state.get("balances") or {}
    return {
        str(exchange): {
            "JPY": _decimal(wallet.get("JPY")),
            "BTC": _decimal(wallet.get("BTC")),
        }
        for exchange, wallet in raw.items()
        if isinstance(wallet, dict)
    }


def _json_ready(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(_json_ready(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _seed_trades(now: datetime, reference_price: Decimal) -> list[dict[str, Any]]:
    pnl_values = [620, 840, -260, 910, 540, -180, 760, 410, -320, 690, 530, 450]
    routes = [
        ("bitbank", "gmocoin"),
        ("coincheck", "bitflyer"),
        ("gmocoin", "bitbank"),
        ("bitflyer", "coincheck"),
    ]
    trades: list[dict[str, Any]] = []
    for index, pnl_value in enumerate(pnl_values):
        buy_exchange, sell_exchange = routes[index % len(routes)]
        timestamp = now - timedelta(days=(len(pnl_values) - index) * 2)
        notional = Decimal("80000") + Decimal(str((index % 4) * 5000))
        quantity = (notional / reference_price).quantize(
            BTC_QUANTUM,
            rounding=ROUND_DOWN,
        )
        net_pnl = Decimal(str(pnl_value))
        net_bps = net_pnl / notional * Decimal("10000")
        fee = notional * Decimal("0.0011")
        slippage = notional * Decimal("0.0004")
        observed_gross = net_bps + (fee + slippage) / notional * Decimal("10000")
        buy_price = reference_price * (
            Decimal("0.998") + Decimal(str(index % 5)) * Decimal("0.001")
        )
        sell_price = buy_price * (Decimal("1") + observed_gross / Decimal("10000"))
        trades.append(
            {
                "id": f"seed-{timestamp.strftime('%Y%m%d')}-{index + 1:02d}",
                "timestamp": timestamp.isoformat(timespec="seconds"),
                "mode": "paper",
                "source": "seeded_demo",
                "market": "BTC/JPY",
                "buy_exchange": buy_exchange,
                "sell_exchange": sell_exchange,
                "quantity_btc": quantity,
                "buy_price_jpy": buy_price,
                "sell_price_jpy": sell_price,
                "buy_notional_jpy": notional,
                "sell_notional_jpy": notional + net_pnl + fee,
                "fees_jpy": fee,
                "slippage_cost_jpy": slippage,
                "observed_gross_spread_bps": observed_gross,
                "execution_gross_spread_bps": observed_gross
                - slippage / notional * Decimal("10000"),
                "net_spread_bps": net_bps,
                "net_pnl_jpy": net_pnl,
                "status": "filled",
            }
        )
    return trades


def _seed_state(
    config: ScannerConfig,
    settings: dict[str, Any],
    reference_price: Decimal,
    now: datetime,
) -> dict[str, Any]:
    exchange_names = [item.name for item in config.exchanges if item.enabled]
    initial_jpy = _decimal(settings.get("initial_jpy_per_exchange"), "500000")
    initial_btc_value = _decimal(
        settings.get("initial_btc_value_jpy_per_exchange"),
        "500000",
    )
    initial_reference = reference_price * Decimal("0.9953")
    balances = initialize_balances(
        exchange_names,
        initial_reference,
        initial_jpy_per_exchange=initial_jpy,
        initial_btc_value_jpy_per_exchange=initial_btc_value,
    )
    initial_capital = (initial_jpy + initial_btc_value) * len(exchange_names)
    trades = _seed_trades(now, reference_price)
    realized_pnl = sum(
        (_decimal(item["net_pnl_jpy"]) for item in trades),
        start=Decimal("0"),
    )
    share = realized_pnl / max(len(exchange_names), 1)
    for wallet in balances.values():
        wallet["JPY"] += share

    final_equity = portfolio_equity(balances, reference_price)
    target_gain = final_equity - initial_capital
    pattern = [
        6200,
        -5800,
        3900,
        -4200,
        7100,
        -6500,
        4800,
        -5200,
        8300,
        -7600,
        3500,
        -4100,
        6900,
        -5900,
        5400,
        -6200,
        7600,
        -6800,
        4300,
        -4700,
        8800,
        -7300,
        5100,
        -5600,
        9700,
        -7800,
        6400,
        -6100,
        10250,
    ]
    pattern_total = Decimal(str(sum(pattern)))
    scale = target_gain / pattern_total if pattern_total else Decimal("0")
    equity = initial_capital
    started_at = now - timedelta(days=len(pattern) + 1)
    history: list[dict[str, Any]] = [
        {
            "timestamp": started_at.replace(hour=23, minute=55).isoformat(timespec="seconds"),
            "equity_jpy": equity,
            "reference_price_jpy": initial_reference,
            "source": "seeded_demo",
        }
    ]
    for index, delta in enumerate(pattern, start=1):
        equity += Decimal(str(delta)) * scale
        progress = Decimal(index) / Decimal(len(pattern))
        point_reference = initial_reference + (reference_price - initial_reference) * progress
        point_time = started_at + timedelta(days=index)
        history.append(
            {
                "timestamp": point_time.replace(hour=23, minute=55).isoformat(timespec="seconds"),
                "equity_jpy": equity,
                "reference_price_jpy": point_reference,
                "source": "seeded_demo",
            }
        )
    history[-1]["equity_jpy"] = final_equity

    return {
        "schema_version": 1,
        "mode": "paper",
        "data_status": "seeded_demo",
        "started_at": started_at.isoformat(timespec="seconds"),
        "initial_capital_jpy": initial_capital,
        "initial_reference_price_jpy": initial_reference,
        "balances": balances,
        "trades": trades,
        "equity_history": history,
        "last_scan": {
            "timestamp": now.isoformat(timespec="seconds"),
            "status": "seeded",
            "errors": {},
        },
    }


def _today_realized_pnl(trades: list[dict[str, Any]], today: str) -> Decimal:
    return sum(
        (
            _decimal(item.get("net_pnl_jpy"))
            for item in trades
            if str(item.get("timestamp", ""))[:10] == today
            and item.get("source") == "public_orderbook_paper"
        ),
        start=Decimal("0"),
    )


def _opportunity_rows(
    opportunities: list[Opportunity],
    risk: PaperRiskConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in opportunities[:12]:
        after_slippage = item.net_spread_bps - risk.slippage_bps * Decimal("2")
        max_quantity = min(
            item.top_size,
            risk.max_trade_jpy / item.buy_ask,
        )
        estimated_profit = item.buy_ask * max_quantity * after_slippage / Decimal("10000")
        rows.append(
            {
                "market": item.market,
                "buy_exchange": item.buy_exchange,
                "sell_exchange": item.sell_exchange,
                "buy_ask_jpy": item.buy_ask,
                "sell_bid_jpy": item.sell_bid,
                "top_size_btc": item.top_size,
                "gross_spread_bps": item.gross_spread_bps,
                "net_spread_bps": item.net_spread_bps,
                "net_after_slippage_bps": after_slippage,
                "estimated_profit_jpy": estimated_profit,
                "eligible": after_slippage >= risk.min_net_bps,
            }
        )
    return rows


def _exchange_rows(
    config: ScannerConfig,
    books: list[OrderBook],
    errors: dict[str, str],
) -> list[dict[str, Any]]:
    books_by_exchange = {book.exchange: book for book in books}
    rows: list[dict[str, Any]] = []
    for item in config.exchanges:
        book = books_by_exchange.get(item.name)
        bid = book.best_bid if book else None
        ask = book.best_ask if book else None
        spread_bps = None
        if bid is not None and ask is not None and ask.price > 0:
            spread_bps = (ask.price - bid.price) / ask.price * Decimal("10000")
        rows.append(
            {
                "id": item.name,
                "name": next(
                    (connector["name"] for connector in CONNECTORS if connector["id"] == item.name),
                    item.name,
                ),
                "status": "connected" if book else "degraded",
                "bid_jpy": bid.price if bid else None,
                "ask_jpy": ask.price if ask else None,
                "spread_bps": spread_bps,
                "taker_fee_bps": item.taker_fee_bps,
                "pair": item.pair,
                "timestamp": book.timestamp if book else None,
                "error": errors.get(item.name),
                "private_api": "not_configured",
            }
        )
    return rows


def _balance_rows(
    balances: dict[str, dict[str, Decimal]],
    reference_price: Decimal,
) -> list[dict[str, Any]]:
    total_equity = portfolio_equity(balances, reference_price)
    rows: list[dict[str, Any]] = []
    for exchange, wallet in sorted(balances.items()):
        btc_value = wallet["BTC"] * reference_price
        total = wallet["JPY"] + btc_value
        cash_ratio = wallet["JPY"] / total * Decimal("100") if total else Decimal("0")
        inventory_status = (
            "balanced" if Decimal("20") <= cash_ratio <= Decimal("80") else "rebalance"
        )
        rows.append(
            {
                "exchange": exchange,
                "jpy": wallet["JPY"],
                "btc": wallet["BTC"],
                "btc_value_jpy": btc_value,
                "total_jpy": total,
                "allocation_pct": total / total_equity * Decimal("100")
                if total_equity
                else Decimal("0"),
                "cash_ratio_pct": cash_ratio,
                "inventory_status": inventory_status,
                "fund_type": "simulated_prefunded",
            }
        )
    return rows


def _build_dashboard(
    state: dict[str, Any],
    config: ScannerConfig,
    balances: dict[str, dict[str, Decimal]],
    books: list[OrderBook],
    errors: dict[str, str],
    opportunities: list[Opportunity],
    reference_price: Decimal,
    risk: PaperRiskConfig,
    settings: dict[str, Any],
    now: datetime,
    execution_reason: str,
    executed_trade: dict[str, Any] | None,
) -> dict[str, Any]:
    initial_capital = _decimal(state.get("initial_capital_jpy"), "4000000")
    trades = list(state.get("trades") or [])
    history = list(state.get("equity_history") or [])
    metrics, daily = calculate_metrics(history, trades, initial_capital)
    live_points = [item for item in history if item.get("source") == "public_orderbook_paper"]
    data_status = "seeded_demo_plus_live_public" if live_points else "seeded_demo"

    return {
        "schema_version": 1,
        "generated_at": now.isoformat(timespec="seconds"),
        "mode": "paper",
        "data_status": data_status,
        "currency": "JPY",
        "market": config.market,
        "repository_visibility": "public",
        "headline": "国内4取引所・事前配賦型アービトラージ ペーパートレード",
        "disclaimer": (
            "シード履歴は画面検証用の仮想データです。以後のスナップショットは公開板を"
            "使いますが、実注文・実残高・送金は行いません。"
        ),
        "current_reference_price_jpy": reference_price,
        "metrics": metrics,
        "balances": _balance_rows(balances, reference_price),
        "equity_history": history[-2000:],
        "daily": daily[-365:],
        "trades": list(reversed(trades[-1000:])),
        "opportunities": _opportunity_rows(opportunities, risk),
        "exchanges": _exchange_rows(config, books, errors),
        "connectors": CONNECTORS,
        "risk": {
            "min_net_bps": risk.min_net_bps,
            "max_trade_jpy": risk.max_trade_jpy,
            "min_trade_jpy": risk.min_trade_jpy,
            "slippage_bps_per_leg": risk.slippage_bps,
            "daily_loss_limit_jpy": risk.daily_loss_limit_jpy,
            "max_trades_per_run": int(settings.get("max_trades_per_run", 1)),
            "withdrawal_enabled": False,
            "live_order_enabled": False,
            "kill_switch": "locked",
            "inventory_model": "pre-funded JPY and BTC on every exchange",
        },
        "assumptions": {
            "price_source": "各取引所Public RESTの板スナップショット",
            "fill_model": "最良気配数量の範囲内＋片側固定スリッページ",
            "transfer_cost": "未計上（取引所間送金を実行しない）",
            "tax": "未計上",
            "benchmark": "BTC在庫の時価変動を含む総資産",
            "fee_values_are_assumptions": True,
        },
        "system": {
            "last_run": now.isoformat(timespec="seconds"),
            "run_status": "degraded" if errors or len(books) < 2 else "healthy",
            "public_exchange_count": len(books),
            "configured_exchange_count": len(config.exchanges),
            "errors": errors,
            "execution_reason": execution_reason,
            "executed_trade_id": executed_trade.get("id") if executed_trade else None,
            "schedule": "GitHub Actionsで毎時17分（UTC）に1回",
            "state_persistence": "data/paper_state.json",
            "secret_storage": "この公開Web画面には保存しない",
        },
    }


async def _run() -> None:
    config_path = (
        SCANNER_CONFIG_PATH if SCANNER_CONFIG_PATH.exists() else ROOT / "config.example.yml"
    )
    config = load_config(config_path)
    settings = _load_paper_settings()
    now = datetime.now(JST)
    books, errors = await fetch_orderbooks(config)

    has_cross_venue_data = len(books) >= 2
    snapshot_source = (
        "public_orderbook_paper" if has_cross_venue_data else "public_orderbook_unavailable"
    )
    snapshot_data_status = "seeded_demo_plus_live_public" if has_cross_venue_data else "seeded_demo"
    existing_state = _load_state()
    if books:
        reference_price = median_reference_price(books)
    elif existing_state:
        history = existing_state.get("equity_history") or []
        reference_price = _decimal(
            history[-1].get("reference_price_jpy") if history else None,
            "10000000",
        )
    else:
        reference_price = Decimal("10000000")

    state = existing_state or _seed_state(config, settings, reference_price, now)
    balances = _decode_balances(state)
    if not balances:
        state = _seed_state(config, settings, reference_price, now)
        balances = _decode_balances(state)

    risk = PaperRiskConfig(
        min_net_bps=_decimal(settings.get("min_net_bps"), "12"),
        max_trade_jpy=_decimal(settings.get("max_trade_jpy"), "50000"),
        min_trade_jpy=_decimal(settings.get("min_trade_jpy"), "2000"),
        slippage_bps=_decimal(settings.get("slippage_bps"), "2"),
        daily_loss_limit_jpy=_decimal(
            settings.get("daily_loss_limit_jpy"),
            "50000",
        ),
    )
    opportunities = calculate_opportunities(
        books,
        config.exchanges,
        min_net_bps=Decimal("-10000"),
    )

    trades = list(state.get("trades") or [])
    today_pnl = _today_realized_pnl(trades, now.date().isoformat())
    execution_reason = (
        "no_eligible_opportunity" if has_cross_venue_data else "insufficient_public_orderbooks"
    )
    executed_trade: dict[str, Any] | None = None
    if today_pnl <= -risk.daily_loss_limit_jpy:
        execution_reason = "daily_loss_limit"
    else:
        max_trades = int(settings.get("max_trades_per_run", 1))
        executions = 0
        for opportunity in opportunities:
            trade, reason = execute_opportunity(
                opportunity,
                books,
                config.exchanges,
                balances,
                risk,
                timestamp=now.isoformat(timespec="seconds"),
            )
            execution_reason = reason
            if trade is None:
                continue
            trades.append(trade)
            executed_trade = trade
            executions += 1
            if executions >= max_trades:
                break

    equity = portfolio_equity(balances, reference_price)
    history = list(state.get("equity_history") or [])
    history.append(
        {
            "timestamp": now.isoformat(timespec="seconds"),
            "equity_jpy": equity,
            "reference_price_jpy": reference_price,
            "source": snapshot_source,
        }
    )
    state.update(
        {
            "data_status": snapshot_data_status,
            "balances": balances,
            "trades": trades[-1000:],
            "equity_history": history[-2000:],
            "last_scan": {
                "timestamp": now.isoformat(timespec="seconds"),
                "status": "degraded" if errors or not has_cross_venue_data else "healthy",
                "errors": errors,
                "execution_reason": execution_reason,
                "executed_trade_id": executed_trade.get("id") if executed_trade else None,
            },
        }
    )
    dashboard = _build_dashboard(
        state,
        config,
        balances,
        books,
        errors,
        opportunities,
        reference_price,
        risk,
        settings,
        now,
        execution_reason,
        executed_trade,
    )
    _write_json(STATE_PATH, state)
    _write_json(DASHBOARD_PATH, dashboard)
    print(
        json.dumps(
            {
                "generated_at": dashboard["generated_at"],
                "portfolio_value_jpy": dashboard["metrics"]["portfolio_value_jpy"],
                "trade_count": dashboard["metrics"]["trade_count"],
                "execution_reason": execution_reason,
                "errors": errors,
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
