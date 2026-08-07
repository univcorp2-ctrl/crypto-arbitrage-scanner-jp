"""Funding-rate arbitrage research and guarded execution primitives."""

from .economics import evaluate_opportunity
from .models import FundingSnapshot, StrategyParameters
from .policy import policy_payload

__all__ = [
    "FundingSnapshot",
    "StrategyParameters",
    "evaluate_opportunity",
    "policy_payload",
]
