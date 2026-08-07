# Security policy

## Public simulation boundary

This repository and its static dashboard are public. They must never receive, store, log, or publish real API keys, real account balances, or personal trading history.

The API setup screen is a transient browser-side guide. Values entered there are not submitted or persisted by this application. Production credentials belong in a non-public backend secret store, GitHub Actions Secrets for read-only jobs, or Cloudflare Worker/Pages secrets. Never place credentials in JavaScript, JSON, repository files, Issues, Actions logs, screenshots, or build output.

## Minimum permissions

Start with account, balance, order, and execution-history read permissions only. Do not grant withdrawal, transfer, or crypto-send permissions. Enable IP restrictions wherever supported. Use a dedicated API key per environment and rotate it after any suspected exposure.

## Live-order gate

`ENABLE_LIVE_ORDERS` remains false. A future live release must add authenticated access, private storage, per-exchange position limits, idempotency, stale-price checks, two-leg execution controls, cancellation recovery, daily loss limits, and an independent kill switch before order permissions are enabled.
