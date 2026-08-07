from __future__ import annotations

import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CredentialField:
    label: str
    env_var: str
    secret: bool = True


@dataclass(frozen=True)
class ExchangeDefinition:
    exchange_id: str
    display_name: str
    registered_as: str
    registration_number: str
    phase: int
    adapter_status: str
    public_pair: str
    docs_url: str
    key_location: str
    credentials: tuple[CredentialField, ...]
    recommended_permissions: tuple[str, ...]
    notes: tuple[str, ...]


def _definition(
    exchange_id: str,
    display_name: str,
    registered_as: str,
    registration_number: str,
    phase: int,
    adapter_status: str,
    public_pair: str,
    docs_url: str,
    key_location: str,
    credentials: tuple[CredentialField, ...],
    recommended_permissions: tuple[str, ...],
    notes: tuple[str, ...],
) -> ExchangeDefinition:
    return ExchangeDefinition(
        exchange_id=exchange_id,
        display_name=display_name,
        registered_as=registered_as,
        registration_number=registration_number,
        phase=phase,
        adapter_status=adapter_status,
        public_pair=public_pair,
        docs_url=docs_url,
        key_location=key_location,
        credentials=credentials,
        recommended_permissions=recommended_permissions,
        notes=notes,
    )


EXCHANGES: tuple[ExchangeDefinition, ...] = (
    _definition(
        "bitbank",
        "bitbank",
        "ビットバンク株式会社",
        "関東財務局長 第00004号",
        1,
        "public-live",
        "btc_jpy",
        "https://github.com/bitbankinc/bitbank-api-docs/blob/master/rest-api_JP.md",
        "ログイン後のAPIキーページ",
        (
            CredentialField("API Key", "BITBANK_API_KEY", secret=False),
            CredentialField("API Secret", "BITBANK_API_SECRET"),
        ),
        ("参照", "現物注文（実運用へ進む段階のみ）", "IP制限"),
        ("出金権限は付与しない", "Time Window方式を優先", "初期接続の最優先候補"),
    ),
    _definition(
        "gmocoin",
        "GMOコイン",
        "GMOコイン株式会社",
        "関東財務局長 第00006号",
        1,
        "public-live",
        "BTC",
        "https://api.coin.z.com/docs/",
        "会員ページのAPI管理",
        (
            CredentialField("API Key", "GMOCOIN_API_KEY", secret=False),
            CredentialField("Secret Key", "GMOCOIN_API_SECRET"),
        ),
        ("参照", "現物注文（実運用へ進む段階のみ）", "IP制限"),
        ("出金権限は付与しない", "Private APIは機能別権限", "WebSocket移行候補"),
    ),
    _definition(
        "bitflyer",
        "bitFlyer",
        "株式会社bitFlyer",
        "関東財務局長 第00003号",
        1,
        "public-live",
        "BTC_JPY",
        "https://lightning.bitflyer.com/docs",
        "Lightningの開発者ページ",
        (
            CredentialField("API Key", "BITFLYER_API_KEY", secret=False),
            CredentialField("API Secret", "BITFLYER_API_SECRET"),
        ),
        ("資産参照", "約定履歴参照", "現物注文（実運用へ進む段階のみ）"),
        ("出金権限は付与しない", "API Secretは平文保存しない", "呼出上限を監視"),
    ),
    _definition(
        "coincheck",
        "Coincheck",
        "コインチェック株式会社",
        "関東財務局長 第00014号",
        1,
        "public-live",
        "btc_jpy",
        "https://coincheck.com/documents/exchange/api",
        "APIキー設定画面",
        (
            CredentialField("Access Key", "COINCHECK_ACCESS_KEY", secret=False),
            CredentialField("Secret Access Key", "COINCHECK_SECRET_KEY"),
        ),
        ("残高参照", "注文参照", "現物注文（実運用へ進む段階のみ）", "IP制限"),
        ("出金・送金権限は付与しない", "Nonceを単調増加", "権限を用途別に分離"),
    ),
    _definition(
        "bittrade",
        "BitTrade",
        "ビットトレード株式会社",
        "関東財務局長 第00007号",
        2,
        "roadmap",
        "btcjpy",
        "https://api-doc.bittrade.co.jp/",
        "マイページ > API > APIキーを作成",
        (
            CredentialField("AccessKey", "BITTRADE_ACCESS_KEY", secret=False),
            CredentialField("SecretKey", "BITTRADE_SECRET_KEY"),
        ),
        ("読取", "取引（実運用へ進む段階のみ）", "IP制限"),
        ("出金権限は付与しない", "まず板・残高の正規化を実装", "流動性を実測して採否判断"),
    ),
    _definition(
        "zaif",
        "Zaif",
        "株式会社Zaif",
        "近畿財務局長 第00001号",
        2,
        "roadmap",
        "btc_jpy",
        "https://zaif-api-document.readthedocs.io/ja/latest/",
        "アカウント > 開発者向けAPI",
        (
            CredentialField("API Key", "ZAIF_API_KEY", secret=False),
            CredentialField("Secret Key", "ZAIF_API_SECRET"),
        ),
        ("Info", "Trade（実運用へ進む段階のみ）", "IP制限"),
        ("Withdraw権限は付与しない", "流動性と板厚を継続測定", "接続は第2段階"),
    ),
    _definition(
        "binancejp",
        "Binance Japan",
        "Binance Japan株式会社",
        "関東財務局長 第00031号",
        2,
        "research",
        "BTC/JPY availability must be checked at runtime",
        "https://developers.binance.com/docs/binance-spot-api-docs/rest-api",
        "アカウント > API管理",
        (
            CredentialField("API Key", "BINANCE_JP_API_KEY", secret=False),
            CredentialField("Secret Key", "BINANCE_JP_API_SECRET"),
        ),
        ("Enable Reading", "Spot Trading（実運用へ進む段階のみ）", "IP制限"),
        ("出金権限は付与しない", "日本向け提供ペアを実行時に照合", "法域と口座条件を再確認"),
    ),
)


def catalog_payload() -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for exchange in EXCHANGES:
        item = asdict(exchange)
        item["configured"] = all(
            bool(os.getenv(field.env_var)) for field in exchange.credentials
        )
        item["secret_values_exposed"] = False
        payload.append(item)
    return payload
