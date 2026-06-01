<!-- AI_README_SETUP_GUIDE_START -->
## 🧭 画像付き初期設定ガイド

![README 画像付き初期設定ガイド](docs/assets/readme-setup-guide.svg)

このリポジトリ **crypto-arbitrage-scanner-jp** を初めて開いた人は、まずここだけ見れば初期設定から実行、成果物確認まで進められます。

### 最初にやること

1. 必要なSecretや外部サービス設定を確認します。
2. GitHub Actions または README の実行手順に沿って動かします。
3. 実行ログと成果物を確認します。
4. エラー時は Actions の失敗ステップと Secret名を確認します。

### 詳しい画像付きガイド

- [docs/setup-visual-guide.md](docs/setup-visual-guide.md)
- [docs/image-generation-prompts.md](docs/image-generation-prompts.md)

> SecretやAPIキーの実値は、README、Issue、ログ、画像に絶対に貼らないでください。例では `********` または `YOUR_SECRET_HERE` を使います。

<!-- AI_README_SETUP_GUIDE_END -->


# Crypto Arbitrage Scanner JP

APIキー不要の Public API だけを使い、国内暗号資産取引所の JPY 建てスポット板を比較する読み取り専用のアービトラージ検知ツールです。

> **重要**: このツールは自動売買を行いません。表示される価格差は、板取得時点の理論値です。実際の約定、レイテンシ、スリッページ、入出金停止、送金時間、手数料変更、税務、規制により損失が出る可能性があります。

## 最初に見るべき取引所

日本在住で JPY 建てから始める前提では、まず以下を監視対象にしています。

| 取引所 | 初期採用理由 | Public API |
|---|---|---|
| bitbank | BTC/JPY の取引所形式、Public REST で ticker/depth が取得しやすい | `https://public.bitbank.cc/{pair}/depth` |
| GMOコイン | 取引手数料が低めで、Public REST/WebSocket API が明確 | `https://api.coin.z.com/public/v1/orderbooks?symbol=BTC` |
| bitFlyer | 国内大手、Lightning の Public API が利用可能 | `https://api.bitflyer.com/v1/board?product_code=BTC_JPY` |
| Coincheck | Public API で板情報を取得可能 | `https://coincheck.com/api/order_books?pair=btc_jpy` |

海外大手の Kraken / Coinbase / OKX などは API や流動性の面では有力ですが、JPY 建て・国内入出金・法域・本人確認・送金時間・為替リスクが絡むため、この初期版では国内 JPY ペアを優先しています。

## セットアップ

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.yml config.yml
```

## 使い方

1回だけスキャン:

```bash
arbscan --config config.yml --market BTC/JPY --min-net-bps 5
```

10秒ごとに監視:

```bash
arbscan --config config.yml --market BTC/JPY --min-net-bps 5 --watch 10
```

## 判定ロジック

各取引所の最良 ask で買い、別取引所の最良 bid で売る前提で、以下を計算します。

```text
buy_cost_per_unit = ask_price * (1 + buy_taker_fee)
sell_proceeds_per_unit = bid_price * (1 - sell_taker_fee)
net_spread = sell_proceeds_per_unit - buy_cost_per_unit
net_spread_bps = net_spread / buy_cost_per_unit * 10000
```

`top_size` は最良 ask/bid の小さい方です。板の2段目以降は初期版では集計していません。

## 設定

`config.example.yml` の `taker_fee_bps` は手数料込み判定用の仮置き値です。実際の口座ランク、銘柄、キャンペーンで変わるため、必ず自分の取引画面・公式手数料ページに合わせて調整してください。

```yaml
market: BTC/JPY
min_net_bps: 5
request_timeout_seconds: 8
exchanges:
  bitbank:
    enabled: true
    taker_fee_bps: 10
    pair: btc_jpy
```

## 安全運用メモ

- 最初は少額・読み取り専用で検証してください。
- 価格差があっても、同時約定できないと片足リスクが出ます。
- 取引所間送金は、チェーン混雑、出金停止、トラベルルール対応、最低出金額で詰まることがあります。
- APIキーを使う場合でも、出金権限は絶対に付けない設計から始めるのが安全です。
- 自動発注は、ドライラン、ポジション上限、APIレート制限、キャンセル失敗、異常価格フィルタ、Kill Switch を入れてから検討してください。

## 参考URL

- bitbank Public API: https://github.com/bitbankinc/bitbank-api-docs/blob/master/public-api.md
- GMO Coin API: https://api.coin.z.com/docs/
- bitFlyer API: https://lightning.bitflyer.com/docs
- Coincheck Exchange API: https://coincheck.com/documents/exchange/api
- 金融庁 暗号資産交換業者登録一覧: https://www.fsa.go.jp/menkyo/menkyoj/kasoutuka.pdf

## 開発

```bash
pip install -e '.[dev]'
pytest
ruff check .
```
