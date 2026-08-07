# 本番相当ペーパートレード運用ガイド

## 現在の安全境界

この実装は **PAPER ONLY** です。公開板の取得は行いますが、実注文、注文取消、出金、Private API 呼出は実装していません。`live` というモード名は API でも拒否します。

起動直後から画面を確認できるよう、45日分の決定論的な仮想履歴をSQLiteへ投入します。履歴の `source` が `synthetic-research-baseline` の行は実市場の約定ではありません。`public-live-paper` で設定ファイルが存在し、公開APIが応答した場合は、公開板を使った仮想約定へ切り替わります。取得失敗時は `synthetic-fallback` と明示して継続します。

## 起動

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
cp config.example.yml config.yml
cp .env.example .env
arbweb --host 127.0.0.1 --port 8000
```

Windows PowerShellでは `.venv\Scripts\Activate.ps1` を使用します。ブラウザで `http://127.0.0.1:8000` を開きます。

Dockerの場合:

```bash
docker build -t arb-ops .
docker run --rm -p 8000:8000 -v "$(pwd)/data:/app/data" arb-ops
```

## 保存されるもの

`ARB_DB_PATH`（標準は `data/arbscanner.db`）へ次を保存します。

- 取引所別のJPY/BTC仮想残高
- 両脚の価格、数量、手数料、スリッページ、レイテンシ、損益、約定状態
- 評価額、期間損益、ドローダウン、基準BTC価格
- 観測した裁定候補と想定発注上限

APIキーやSecretはSQLiteへ保存しません。Webの入力欄は環境変数ブロックをローカル生成するだけで、サーバーへ送信しません。

## 指標定義

- **総資産評価額**: 全取引所のJPY + BTC数量 × 最新基準価格
- **日次増減**: 各UTC日終値の評価額差
- **実現損益**: 約定した二脚の売却代金 − 購入代金 − 両取引所手数料
- **最大ドローダウン**: 日次評価額の過去最高値からの最大下落率
- **Sharpe ratio**: 日次平均リターン ÷ 日次標準偏差 × √365（無リスク金利0）
- **Sortino ratio**: 日次平均リターン ÷ 下方偏差 × √365
- **Calmar ratio**: 年率換算リターン ÷ 最大ドローダウン絶対値
- **Profit Factor**: 利益取引合計 ÷ 損失取引絶対値合計
- **Fill ratio**: filled/partial件数 ÷ 全試行件数

固定BTC在庫を保有するため、評価額にはBTC価格変動も反映されます。純粋な裁定収益だけを見る場合は `strategy_pnl_jpy` を確認してください。

## 本番移行ゲート

実資金接続は、少なくとも次を満たすまで行いません。

1. 30日以上の無停止ペーパートレードとデータ欠損監視
2. 最小注文数量、価格刻み、数量精度、メンテナンス状態の取引所別検証
3. 二脚の片側のみ約定した場合のヘッジ、取消失敗、再試行、冪等性テスト
4. 口座別残高予約、日次損失上限、取引上限、異常価格、レート制限の統合テスト
5. 出金権限なし、IP制限あり、用途分離された注文専用APIキー
6. Secret Manager、監査ログ、アラート、時刻同期、障害時Kill switch
7. 税務・会計・利用規約・法域・トラベルルールの確認

## API

- `GET /api/overview`: 指標、残高、日次推移、履歴、裁定候補
- `GET /api/exchanges`: 接続計画と環境変数名（Secret値は返さない）
- `POST /api/simulation/start|stop|tick|reset`
- `PUT /api/risk`: ペーパートレード制限
- `PUT /api/mode`: `public-live-paper` または `synthetic-replay`
- `PUT /api/kill-switch`: 新規仮想約定を停止
- `GET /healthz`: 最小ヘルス情報
