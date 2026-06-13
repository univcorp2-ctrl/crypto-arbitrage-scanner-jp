# ✅ SETUP_CHECKLIST — crypto-arbitrage-scanner-jp

> AI調査日: 2026-06-14 | 担当: AI自動生成

## 概要
BTC/JPY市場で4取引所（ビットバンク・GMOコイン・ビットフライヤー・コインチェック）の板情報を30分ごとにスㆭャンし、裁定機会をTelegram通知するPythonスクリプト。
**読み取り専用・発注機能なし・取引所APIキー不要。**

---

## 🤖 AI完了済み

- [x] `CF_WORKER_SECRET` → GitHub Repository Secretsに登録済み（2026-06-14）
- [x] config.example.ymlはワークフローが自動でconfig.ymlにコピー（変更不要）

---

## 👤 Hiro対応（必須・5分）

### Step 1: GitHub Actions を有効化
1. このリポジトリ → **Settings** → **Actions** → **General**
2. **Allow all actions and reusable workflows** を選択
3. **Save**

### Step 2: 動作確認
- Actions タブ → **Arb Scanner - Schedule and Notify** → **Run workflow**（手動実行）
- ログに `Opportunity found` または `No opportunity` が出れば成功
- 30分後に自動実行が始まる

---

## 📡 通知先
Telegram chat_id: `8245984960` へ裁定機会発生時に通知

## ⚙️ 実行スケジ�%ール
`*/30 * * * *`（30分ごつ）

## 📋 	�*Eな�icrets一殧
| Secret名 | 値 | 状煋 |
|---|---|---|
| `CF_WORKER_SECRET` | Cloudflare Worker⪍証キー | ✅ 登録済み |
