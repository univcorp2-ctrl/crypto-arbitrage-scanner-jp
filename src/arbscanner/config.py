from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from .models import ExchangeConfig


@dataclass(frozen=True)
class ScannerConfig:
    market: str
    min_net_bps: Decimal
    request_timeout_seconds: float
    exchanges: tuple[ExchangeConfig, ...]


def load_config(path: str | Path) -> ScannerConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError("configuration root must be a mapping")

    market = str(raw.get("market") or "BTC/JPY")
    min_net_bps = Decimal(str(raw.get("min_net_bps", 0)))
    request_timeout_seconds = float(raw.get("request_timeout_seconds", 8))
    exchange_configs = _parse_exchanges(raw.get("exchanges") or {})

    if not exchange_configs:
        raise ValueError("no exchanges are configured")

    return ScannerConfig(
        market=market,
        min_net_bps=min_net_bps,
        request_timeout_seconds=request_timeout_seconds,
        exchanges=tuple(exchange_configs),
    )


def _parse_exchanges(raw_exchanges: Any) -> list[ExchangeConfig]:
    if not isinstance(raw_exchanges, dict):
        raise ValueError("exchanges must be a mapping")

    parsed: list[ExchangeConfig] = []
    for name, raw_item in raw_exchanges.items():
        if not isinstance(raw_item, dict):
            raise ValueError(f"exchange config for {name!r} must be a mapping")
        parsed.append(
            ExchangeConfig(
                name=str(name),
                enabled=bool(raw_item.get("enabled", True)),
                pair=str(raw_item.get("pair") or ""),
                taker_fee_bps=Decimal(str(raw_item.get("taker_fee_bps", 0))),
            )
        )
    return parsed
