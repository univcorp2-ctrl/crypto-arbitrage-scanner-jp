# Paper trading operations

## What is running

The scheduled workflow fetches the public BTC/JPY order book from bitbank, GMO Coin, bitFlyer, and Coincheck. It evaluates cross-exchange buy/sell routes after the configured taker-fee assumptions and a fixed slippage allowance. When the post-cost spread exceeds the threshold and both simulated wallets have enough prefunded JPY/BTC, one paper trade is recorded.

No real order, transfer, withdrawal, or private account call is performed.

## Ledger model

Each venue starts with simulated JPY and BTC. A paper arbitrage buys BTC on one venue and sells the same quantity on another. This preserves total BTC but shifts inventory between venues. The dashboard therefore shows both strategy realized PnL and inventory mark-to-market PnL.

## Default risk controls

- Minimum post-cost spread: 5 bps
- Maximum notional per run: JPY 100,000
- Minimum notional: JPY 5,000
- Slippage assumption: 2 bps per leg
- Daily realized loss stop: JPY 50,000
- Maximum fills per scheduled run: 1
- Withdrawal and live-order gates: disabled

Edit `paper.example.yml` to change simulation assumptions. A configuration change does not enable real trading.

## Data quality labels

- `seeded_demo`: deterministic hypothetical history used to exercise charts and metrics.
- `seeded_demo_plus_live_public`: demo history plus scheduled public-order-book snapshots and any resulting paper fills.

The seeded history must not be interpreted as evidence of expected returns.

## Metrics

The dashboard calculates total and daily PnL, total/annualized return, Sharpe, Sortino, Calmar, annualized volatility, maximum drawdown, win rate, profit factor, fees, slippage, best/worst day, and realized versus inventory mark-to-market PnL.
