# Paper trading operations

## What is running

The scheduled workflow fetches the public BTC/JPY order book from bitbank, GMO Coin, bitFlyer, and Coincheck. It evaluates cross-exchange buy/sell routes after configured taker-fee assumptions and fixed slippage. When the post-cost spread exceeds the threshold and both simulated wallets have enough prefunded JPY/BTC, at most one paper trade is recorded per run.

No real order, transfer, withdrawal, or private account call is performed.

## Ledger model

Each venue starts with simulated JPY and BTC. A paper arbitrage buys BTC on one venue and sells the same quantity on another. This preserves total BTC but shifts inventory between venues. The dashboard therefore separates strategy realized PnL from inventory mark-to-market PnL.

## Default risk controls

- Minimum post-cost spread: 12 bps
- Maximum notional per run: JPY 50,000
- Minimum notional: JPY 2,000
- Slippage assumption: 2 bps per leg
- Daily realized loss stop: JPY 50,000
- Maximum fills per scheduled run: 1
- Withdrawal and live-order gates: disabled

Edit `paper.example.yml` to change scheduled simulation assumptions. A configuration change cannot enable real trading because no live-order router exists.

## Data quality labels

- `seeded_demo`: deterministic hypothetical history used to exercise charts and metrics.
- `seeded_demo_plus_live_public`: demo history plus at least one cross-venue public-order-book snapshot.
- `public_orderbook_paper`: a snapshot calculated from at least two public venues.
- `public_orderbook_unavailable`: fewer than two public venues were available; no fill is recorded.

The seeded history must not be interpreted as evidence of expected returns.

## Metrics

The dashboard calculates total and daily PnL, total and annualized return, Sharpe, Sortino, Calmar, annualized volatility, maximum drawdown, win rate, profit factor, fees, slippage, best/worst day, and realized versus inventory mark-to-market PnL.
