# 取引所API接続計画とキー配置

調査日: 2026-08-07

この文書は、ペーパートレードから少額実運用へ進む前の接続設計です。現行コードは**公開板の取得とペーパー約定だけ**を行い、認証付き注文・出金は実装していません。

## 接続優先順位

| 段階 | 取引所 | 公開板 | ペーパー | 認証API調査 | 次の実装 |
|---|---|---:|---:|---:|---|
| 1 | bitbank | 実装済み | 対応 | 完了 | 残高参照アダプター |
| 1 | GMOコイン | 実装済み | 対応 | 完了 | 残高参照アダプター |
| 1 | bitFlyer | 実装済み | 対応 | 完了 | 残高参照アダプター |
| 1 | Coincheck | 実装済み | 対応 | 完了 | 残高参照アダプター |
| 2 | OKJ | 未実装 | 未対応 | 完了 | 公開板アダプター |
| 2 | Zaif | 未実装 | 未対応 | 完了 | 公開板アダプター |

初期4社は、既存の公開板アダプターを流用でき、JPY現物BTCの比較をすぐ継続できるため優先します。追加2社は、板の正規化、手数料体系、最小注文数量、レート制限をテストしてから組み込みます。

## サーバーに置く環境変数

```dotenv
BITBANK_API_KEY=YOUR_SECRET_HERE
BITBANK_API_SECRET=YOUR_SECRET_HERE

GMO_COIN_API_KEY=YOUR_SECRET_HERE
GMO_COIN_API_SECRET=YOUR_SECRET_HERE

BITFLYER_API_KEY=YOUR_SECRET_HERE
BITFLYER_API_SECRET=YOUR_SECRET_HERE

COINCHECK_API_KEY=YOUR_SECRET_HERE
COINCHECK_API_SECRET=YOUR_SECRET_HERE

# 次段候補
OKJ_API_KEY=YOUR_SECRET_HERE
OKJ_API_SECRET=YOUR_SECRET_HERE
OKJ_API_PASSPHRASE=YOUR_SECRET_HERE
ZAIF_API_KEY=YOUR_SECRET_HERE
ZAIF_API_SECRET=YOUR_SECRET_HERE
```

画面の「取引所・API接続」では、キー値をサーバーへ送らず、この形式のテンプレートだけをブラウザ内で生成します。アプリのAPIは環境変数の**有無だけ**を返し、値は返しません。

## 取引所側の発行方針

1. 参照権限だけで残高取得を確認する。
2. 固定IPが用意できる場合は許可IPを限定する。
3. 注文権限は、ペーパー実績、少額上限、日次損失上限、停止スイッチを検証した後に追加する。
4. 出金・送付権限は付与しない。
5. キーを取引所ごとに分離し、用途名と発行日を記録する。
6. ローテーション時は旧キーを停止してから新キーへ切り替える。

## 公式仕様

- bitbank API docs: https://github.com/bitbankinc/bitbank-api-docs
- GMOコイン API: https://api.coin.z.com/docs/
- bitFlyer Lightning API: https://lightning.bitflyer.com/docs
- Coincheck Exchange API: https://coincheck.com/documents/exchange/api
- OKJ API v5: https://www.okj.com/docs-v5/ja/
- Zaif API: https://zaif-api-document.readthedocs.io/ja/latest/

## 実運用へ進む順序

1. 公開板の欠損率・遅延・レート制限を7日以上記録する。
2. 認証APIは残高参照のみを実装する。
3. 取引所画面の残高とローカル台帳を毎日照合する。
4. 注文生成は行うが送信しない「shadow order」を記録する。
5. 最小額のIOC/指値で片側約定、取消、部分約定を検証する。
6. 両建て失敗時のヘッジ、再配分、停止条件を検証する。
7. 日次損失上限と総建玉上限を満たす範囲でのみ少額運用する。
