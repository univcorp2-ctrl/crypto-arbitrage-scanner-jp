# Security policy

## Public simulation boundary

This repository and its static dashboard are public. They must never receive, store, log, or publish real API keys, real account balances, personal trading history, private exchange responses, or withdrawal addresses.

The API setup screens are transient browser-side helpers. They do not submit or persist values. Production credentials belong in a non-public backend secret store, GitHub Actions Secrets for read-only jobs, or an encrypted platform secret manager. Never place credentials in JavaScript, JSON, repository files, Issues, Actions logs, screenshots, or build output.

## Local control plane

The FastAPI operations console binds to `127.0.0.1` by default, and Docker Compose publishes only `127.0.0.1:8000`. Its mutating paper endpoints are intended for a trusted local operator. Do not expose this control plane directly to the public internet. Add authenticated access, CSRF/origin controls, TLS, audit identity, and a private data store before any remote deployment.

## Minimum exchange permissions

Start with account, balance, order, and execution-history read permissions only. Do not grant withdrawal, transfer, crypto-send, or fiat-withdrawal permissions. Enable IP restrictions wherever supported. Use a dedicated API key per environment and rotate it after any suspected exposure.

## Live-order gate

There is no live-order router in this repository. A future live release must add authenticated access, private storage, per-exchange and portfolio limits, idempotency, stale-price checks, clock-drift checks, two-leg execution controls, cancellation and partial-fill recovery, daily loss limits, an independent kill switch, and exchange-specific minimum-order tests before order permissions are enabled.
