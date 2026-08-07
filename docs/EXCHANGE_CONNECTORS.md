# Exchange connector plan

Last reviewed: 2026-08-07 (JST)

## Recommended rollout order

| Priority | Venue | Current stage | Private authentication | Simulation fee assumption |
|---:|---|---|---|---:|
| 1 | bitbank | Public板・paper接続済み | `ACCESS-KEY`, request time/nonce, HMAC-SHA256 signature | 10 bps |
| 2 | GMOコイン | Public板・paper接続済み | `API-KEY`, `API-TIMESTAMP`, `API-SIGN` | 5 bps |
| 3 | bitFlyer Lightning | Public板・paper接続済み | `ACCESS-KEY`, `ACCESS-TIMESTAMP`, `ACCESS-SIGN` | 15 bps（保守値） |
| 4 | Coincheck Exchange | Public板・paper接続済み | `ACCESS-KEY`, `ACCESS-NONCE`, `ACCESS-SIGNATURE` | 0 bps（仮定） |
| 5 | BitTrade | 調査済み・次段 | API key / secret、署名認証 | 未設定 |
| 6 | OKJ | 調査済み・次段 | API key / secret / passphrase | 未設定 |
| 7 | Zaif | 調査済み・次段 | key / HMAC signature | 未設定 |

手数料値はシミュレーション入力であり、将来の収益を示しません。口座ランク、ペア、キャンペーン、公式手数料ページと一致させてください。

## Secret names

| Venue | API key | API secret / passphrase |
|---|---|---|
| bitbank | `BITBANK_API_KEY` | `BITBANK_API_SECRET` |
| GMOコイン | `GMO_COIN_API_KEY` | `GMO_COIN_API_SECRET` |
| bitFlyer | `BITFLYER_API_KEY` | `BITFLYER_API_SECRET` |
| Coincheck | `COINCHECK_API_KEY` | `COINCHECK_API_SECRET` |
| BitTrade | `BITTRADE_API_KEY` | `BITTRADE_API_SECRET` |
| OKJ | `OKJ_API_KEY` | `OKJ_API_SECRET`, `OKJ_API_PASSPHRASE` |
| Zaif | `ZAIF_API_KEY` | `ZAIF_API_SECRET` |

ローカル開発ではGit管理外の `.env`、GitHub ActionsではRepository Secrets、ホスト型バックエンドでは暗号化Secretへ登録します。公開Pages変数、フロントエンドJavaScript、JSON、ログへ値を出しません。

## Permissions by phase

1. **Public market data**: キー不要。現在の定期実行モード。
2. **Private read-only**: 残高、未約定注文、約定履歴だけ。出金・振替・暗号資産送付は無効。
3. **Paper with private balances**: 実残高で発注意図を計算するが、注文を送らない。公開JSONではなく非公開DBへ保存。
4. **Limited live orders**: 専用キー、IP許可リスト、厳格な金額・日次損失上限、二脚回復、認証付き管理画面、独立Kill Switchが必要。

## Official references

- bitbank API: https://github.com/bitbankinc/bitbank-api-docs
- GMOコイン API: https://api.coin.z.com/docs/
- bitFlyer Lightning API: https://lightning.bitflyer.com/docs
- Coincheck Exchange API: https://coincheck.com/documents/exchange/api
- BitTrade API: https://api-doc.bittrade.co.jp/
- OKJ API v5: https://www.okj.com/docs-v5/ja/
- Zaif API: https://zaif-api-document.readthedocs.io/ja/latest/
