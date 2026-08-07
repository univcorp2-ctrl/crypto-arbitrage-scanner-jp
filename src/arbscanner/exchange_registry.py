from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ExchangeVenue:
    id: str
    name: str
    stage: str
    public_market_data: bool
    paper_ready: bool
    private_adapter_status: str
    default_pair: str
    api_docs_url: str
    credential_env: tuple[str, ...]
    key_issuance_note: str
    recommended_permissions: tuple[str, ...]
    ip_allowlist_recommended: bool
    notes: str


EXCHANGE_VENUES: tuple[ExchangeVenue, ...] = (
    ExchangeVenue(
        id="bitbank",
        name="bitbank",
        stage="paper_connected",
        public_market_data=True,
        paper_ready=True,
        private_adapter_status="researched_not_implemented",
        default_pair="btc_jpy",
        api_docs_url="https://github.com/bitbankinc/bitbank-api-docs",
        credential_env=("BITBANK_API_KEY", "BITBANK_API_SECRET"),
        key_issuance_note="bitbankのAPI管理画面で発行し、サーバー環境変数へ登録します。",
        recommended_permissions=("資産参照", "現物注文（将来のみ）"),
        ip_allowlist_recommended=True,
        notes="公開板アダプターは実装済み。秘密鍵をブラウザやGitへ保存しません。",
    ),
    ExchangeVenue(
        id="gmocoin",
        name="GMOコイン",
        stage="paper_connected",
        public_market_data=True,
        paper_ready=True,
        private_adapter_status="researched_not_implemented",
        default_pair="BTC",
        api_docs_url="https://api.coin.z.com/docs/",
        credential_env=("GMO_COIN_API_KEY", "GMO_COIN_API_SECRET"),
        key_issuance_note="GMOコインのAPI設定で参照権限から開始し、環境変数へ登録します。",
        recommended_permissions=("参照", "現物注文（将来のみ）"),
        ip_allowlist_recommended=True,
        notes="公開板アダプターは実装済み。出金権限は付与しない方針です。",
    ),
    ExchangeVenue(
        id="bitflyer",
        name="bitFlyer",
        stage="paper_connected",
        public_market_data=True,
        paper_ready=True,
        private_adapter_status="researched_not_implemented",
        default_pair="BTC_JPY",
        api_docs_url="https://lightning.bitflyer.com/docs",
        credential_env=("BITFLYER_API_KEY", "BITFLYER_API_SECRET"),
        key_issuance_note="bitFlyer LightningのAPI画面で発行し、環境変数へ登録します。",
        recommended_permissions=("資産残高を取得", "注文を出す（将来のみ）"),
        ip_allowlist_recommended=True,
        notes="現物BTC_JPYだけを対象とし、CFDは対象外です。",
    ),
    ExchangeVenue(
        id="coincheck",
        name="Coincheck",
        stage="paper_connected",
        public_market_data=True,
        paper_ready=True,
        private_adapter_status="researched_not_implemented",
        default_pair="btc_jpy",
        api_docs_url="https://coincheck.com/documents/exchange/api",
        credential_env=("COINCHECK_API_KEY", "COINCHECK_API_SECRET"),
        key_issuance_note="CoincheckのAPIキー設定で発行し、環境変数へ登録します。",
        recommended_permissions=("残高", "新規注文・取消（将来のみ）"),
        ip_allowlist_recommended=True,
        notes="公開板アダプターは実装済み。出金APIは接続対象外です。",
    ),
    ExchangeVenue(
        id="okj",
        name="OKJ",
        stage="researched_next",
        public_market_data=False,
        paper_ready=False,
        private_adapter_status="roadmap",
        default_pair="BTC-JPY",
        api_docs_url="https://www.okj.com/docs-v5/ja/",
        credential_env=("OKJ_API_KEY", "OKJ_API_SECRET", "OKJ_API_PASSPHRASE"),
        key_issuance_note="OKJのAPI管理画面でキーとパスフレーズを発行します。",
        recommended_permissions=("読み取り", "取引（将来のみ）"),
        ip_allowlist_recommended=True,
        notes="REST/WebSocket仕様を調査済み。板アダプター実装後に追加します。",
    ),
    ExchangeVenue(
        id="zaif",
        name="Zaif",
        stage="researched_next",
        public_market_data=False,
        paper_ready=False,
        private_adapter_status="roadmap",
        default_pair="btc_jpy",
        api_docs_url="https://zaif-api-document.readthedocs.io/ja/latest/",
        credential_env=("ZAIF_API_KEY", "ZAIF_API_SECRET"),
        key_issuance_note="ZaifのAPIキー管理で発行し、環境変数へ登録します。",
        recommended_permissions=("info", "trade（将来のみ）"),
        ip_allowlist_recommended=True,
        notes="公開・現物取引APIを調査済み。次段の接続候補です。",
    ),
)


def public_exchange_registry() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for venue in EXCHANGE_VENUES:
        row = asdict(venue)
        configured = [name for name in venue.credential_env if bool(os.getenv(name))]
        missing = [name for name in venue.credential_env if not os.getenv(name)]
        row["credential_env"] = list(venue.credential_env)
        row["recommended_permissions"] = list(venue.recommended_permissions)
        row["credential_status"] = {
            "configured": len(configured) == len(venue.credential_env),
            "configured_count": len(configured),
            "required_count": len(venue.credential_env),
            "missing": missing,
        }
        result.append(row)
    return result
