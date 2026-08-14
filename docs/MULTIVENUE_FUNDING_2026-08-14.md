# Multi-venue funding arbitrage — Japan control plane

Evidence date: 2026-08-14.

## Implemented connectors

The new `fundingmulti` console uses CCXT public/private REST normalization for **MEXC, Gate, Bitrue and Bitget**. The existing direct bitFlyer implementation remains the domestic primary path. OKX and BingX are represented as public-research-only because current published compliance material contains Japan restrictions relevant to their services.

The engine scans `BTC/USDT:USDT` perpetuals, records funding, depth and next-settlement data, and ranks **perp-perp funding spread** trades: long the lower-funding perpetual and short the higher-funding perpetual. It also exposes the calculation primitive for cash-and-carry (spot long + perpetual short).

## Japan status is deliberately product-specific

A website being reachable in Japan does not prove that a Japanese resident is eligible for every derivatives product. MEXC currently has Japan-facing material but also publishes product announcements that list Japan as restricted. Bitrue explicitly restricts Japan for its TradFi service while offering crypto futures APIs. Gate offers a comprehensive futures API, but Japan-resident live eligibility is not assumed. Bitget currently publishes Japan onboarding pages, but this system still requires account/product attestation before derivatives live routing.

For those reasons, offshore venues are **scan-enabled but live-disabled by default**. To promote one venue, all of these must pass:

- `FUNDING_MULTI_LIVE_ENABLED=true`
- `FUNDING_<VENUE>_LIVE_ENABLED=true`
- `FUNDING_MULTI_MAX_LIVE_NOTIONAL_USDT` cap
- `FUNDING_<VENUE>_JP_ELIGIBILITY_ATTESTED=YYYY-MM-DD` refreshed within 30 days
- encrypted vault credentials verified by a private balance call
- market active and supported
- sufficient USDT buffer and position query
- kill switch OFF
- opportunity profitability/depth gates

## Execution

Perp-perp entry sends the **short funding leg first** as an FOK limit, then the long leg as FOK. If the second leg fails, the executor attempts an FOK close of the first leg. It never falls back to an unbounded market order. An incomplete compensation is surfaced as an incident for manual reconciliation.

No withdrawal/send-coin endpoint exists. Cross-exchange capital movement is intentionally outside the trading-key trust boundary.

## Sources

- FSA registered crypto-asset exchange list: https://www.fsa.go.jp/menkyo/menkyoj/kasoutuka.pdf
- JVCEA members/derivatives status: https://jvcea.or.jp/member/
- MEXC futures API: https://www.mexc.com/api-docs/futures/market-endpoints/get-funding-rate
- MEXC product restriction example: https://www.mexc.com/announcements/article/introducing-futures-innovation-zone-17827791534000
- Gate API v4: https://www.gate.com/docs/developers/apiv4/en/
- Bitrue Futures OpenAPI: https://support.bitrue.com/hc/en-001/articles/6643403350553-OpenAPI-and-Big-Data-Functions-Added-to-Futures
- Bitrue regional TradFi disclaimer: https://support.bitrue.com/hc/en-001/articles/56552373148313-Important-Disclaimer-TradFi-Futures-Services
- Bitget Japan onboarding page: https://www.bitget.com/how-to-buy/world-cup-2026-official-song/japan
- OKX restricted locations: https://www.okx.com/help/risk-compliance-disclosure
- BingX CFD regional restrictions: https://bingx.com/en/support/articles/17088995856271
- CCXT supported exchanges: https://github.com/ccxt/ccxt/wiki/Exchange-Markets
