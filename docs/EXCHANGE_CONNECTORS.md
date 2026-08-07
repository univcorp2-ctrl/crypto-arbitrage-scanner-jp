# Exchange connector plan

Last reviewed: 2026-08-07 (JST)

## Recommended rollout order

| Priority | Venue | Public market data | Private authentication | Simulation fee assumption |
|---|---|---|---|---:|
| 1 | bitbank | `public.bitbank.cc` | `ACCESS-KEY`, request time/nonce, HMAC-SHA256 signature | 10 bps |
| 2 | GMO Coin | Public REST/WebSocket | `API-KEY`, `API-TIMESTAMP`, `API-SIGN` | 5 bps |
| 3 | bitFlyer Lightning | Public HTTP/Realtime API | `ACCESS-KEY`, `ACCESS-TIMESTAMP`, `ACCESS-SIGN` | 15 bps, conservative |
| 4 | Coincheck Exchange | Public REST/WebSocket | `ACCESS-KEY`, `ACCESS-NONCE`, `ACCESS-SIGNATURE` | 0 bps assumption |

Fee values are simulation inputs, not promises. They must be checked against the account tier, pair, campaign, and official fee page before any production decision.

## Secret names

| Venue | API key | API secret |
|---|---|---|
| bitbank | `BITBANK_API_KEY` | `BITBANK_API_SECRET` |
| GMO Coin | `GMO_API_KEY` | `GMO_API_SECRET` |
| bitFlyer | `BITFLYER_API_KEY` | `BITFLYER_API_SECRET` |
| Coincheck | `COINCHECK_API_KEY` | `COINCHECK_API_SECRET` |

Use `.env` only for local development and keep it out of Git. For GitHub Actions, create repository Actions Secrets with the exact names above. For a Cloudflare backend, create encrypted project/Worker secrets. Do not expose secrets as public Pages environment variables or frontend JavaScript.

## Permissions by phase

1. **Public market data**: no keys. This is the currently active mode.
2. **Private read-only**: balance, active order, and execution-history access only. Withdrawal/transfer/crypto-send must remain disabled.
3. **Paper execution with real balances**: calculate intended orders but submit none. Store results in a private data store, not this public dashboard.
4. **Limited live orders**: dedicated keys, IP allowlist, strict notional and daily-loss limits, two-leg recovery, and a kill switch.

## Official references

- bitbank Private REST API: https://github.com/bitbankinc/bitbank-api-docs/blob/master/rest-api.md
- GMO Coin API: https://api.coin.z.com/docs/
- bitFlyer Lightning API: https://lightning.bitflyer.com/docs
- Coincheck Exchange API: https://coincheck.com/documents/exchange/api
