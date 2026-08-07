# 国内取引所API接続調査と設定方針

調査日: 2026-08-07  
登録状況の基準: 金融庁「暗号資産交換業者登録一覧」令和8年6月30日現在

## 接続順序

### Phase 1: 既存Public Adapterを運用監視へ統合

| 取引所 | 登録番号 | Public pair | 画面に表示する環境変数 | 現状 |
|---|---|---|---|---|
| bitbank | 関東財務局長 第00004号 | `btc_jpy` | `BITBANK_API_KEY`, `BITBANK_API_SECRET` | Public板接続済み |
| GMOコイン | 関東財務局長 第00006号 | `BTC` | `GMOCOIN_API_KEY`, `GMOCOIN_API_SECRET` | Public板接続済み |
| bitFlyer | 関東財務局長 第00003号 | `BTC_JPY` | `BITFLYER_API_KEY`, `BITFLYER_API_SECRET` | Public板接続済み |
| Coincheck | 関東財務局長 第00014号 | `btc_jpy` | `COINCHECK_ACCESS_KEY`, `COINCHECK_SECRET_KEY` | Public板接続済み |

Phase 1ではAPIキー不要の板情報だけで本番相当ペーパートレードを行います。Private APIは残高・約定履歴の照合を実装する段階まで使いません。

### Phase 2: 板厚と実効コストを実測して追加

| 取引所 | 登録番号 | 環境変数 | 採否条件 |
|---|---|---|---|
| BitTrade | 関東財務局長 第00007号 | `BITTRADE_ACCESS_KEY`, `BITTRADE_SECRET_KEY` | BTC/JPY板厚、レート制限、数量精度を実測 |
| Zaif | 近畿財務局長 第00001号 | `ZAIF_API_KEY`, `ZAIF_API_SECRET` | 板厚、障害率、約定品質を実測 |
| Binance Japan | 関東財務局長 第00031号 | `BINANCE_JP_API_KEY`, `BINANCE_JP_API_SECRET` | 日本口座で提供されるJPYペアを実行時照合 |

「銘柄を扱っている」ことと「取引所形式のJPY板がAPI提供されている」ことは別です。接続時に markets/symbols endpoint、最小数量、価格刻み、注文種別、メンテナンス状態を必ず機械照合します。

## 取引所別の認証要点

- **bitbank**: `ACCESS-KEY` とHMAC-SHA256署名。Time Window方式が利用可能。取得系と更新系にレート制限があります。
- **GMOコイン**: `API-KEY`, `API-TIMESTAMP`, `API-SIGN`。機能別権限とIP制限を設定できます。
- **bitFlyer**: `ACCESS-KEY`, `ACCESS-TIMESTAMP`, `ACCESS-SIGN`。API Keyごとに権限を設定できます。
- **Coincheck**: `ACCESS-KEY`, 単調増加する `ACCESS-NONCE`, `ACCESS-SIGNATURE`。機能別権限とIP制限があります。
- **BitTrade**: AccessKey/SecretKey。読取、取引、出金の権限が分離されています。
- **Zaif**: API Key/Secret Key。Info/Trade/Withdrawを分離し、Withdrawは付けません。
- **Binance Japan**: API Key/Secret Key。ReadingとSpot Tradingを分離し、IP制限を必須とします。

## キー発行ポリシー

1. 最初のキーは読取専用にする
2. 注文実装時は別の注文専用キーを作る
3. 出金・送金権限は常に無効
4. 固定IPまたは許可IPリストを設定
5. キーをリポジトリ、Issue、ログ、SQLite、スクリーンショットへ残さない
6. 本番サーバーの環境変数またはSecret Managerから注入
7. 90日以内のローテーションと漏えい時即時失効手順を準備

## 公式資料

- 金融庁登録一覧: `https://www.fsa.go.jp/menkyo/menkyoj/kasoutuka.pdf`
- bitbank API: `https://github.com/bitbankinc/bitbank-api-docs/blob/master/rest-api_JP.md`
- GMOコイン API: `https://api.coin.z.com/docs/`
- bitFlyer Lightning API: `https://lightning.bitflyer.com/docs`
- Coincheck Exchange API: `https://coincheck.com/documents/exchange/api`
- BitTrade API: `https://api-doc.bittrade.co.jp/`
- Zaif API: `https://zaif-api-document.readthedocs.io/ja/latest/`
- Binance Spot API: `https://developers.binance.com/docs/binance-spot-api-docs/rest-api`
