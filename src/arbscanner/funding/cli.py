from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .bitflyer import BitflyerPublicClient
from .economics import evaluate_opportunity
from .models import StrategyParameters


async def _run(output: str | None) -> int:
    client = BitflyerPublicClient()
    try:
        snapshot, history = await asyncio.gather(client.snapshot(), client.funding_history(30))
        result = evaluate_opportunity(snapshot, StrategyParameters())
        payload = {
            "source": "bitflyer_public_api",
            "snapshot": snapshot.to_dict(),
            "history": [point.to_dict() for point in history],
            "evaluation": result.to_dict(),
            "real_order_submission": False,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if output:
            target = Path(output)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)
        return 0
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture a public bitFlyer funding snapshot.")
    parser.add_argument("--output", help="Optional JSON output path")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args.output)))


if __name__ == "__main__":
    main()
