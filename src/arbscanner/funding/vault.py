from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class VaultUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CredentialStatus:
    venue: str
    configured: bool
    active: bool
    updated_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "venue": self.venue,
            "configured": self.configured,
            "active": self.active,
            "updated_at": self.updated_at,
            "secret_values_returned": False,
        }


class CredentialVault:
    """Small encrypted local vault.

    The encryption key must come from FUNDING_VAULT_KEY or an equivalent host secret. The key
    is never written to the database. Records are disabled rather than physically deleted.
    """

    def __init__(self, path: str | Path, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode())
        except (TypeError, ValueError) as exc:
            raise VaultUnavailable("FUNDING_VAULT_KEY is invalid") from exc
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS funding_credentials (
                    venue TEXT PRIMARY KEY,
                    ciphertext BLOB NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save(self, venue: str, api_key: str, api_secret: str) -> CredentialStatus:
        if not venue or not api_key or not api_secret:
            raise ValueError("venue, api_key, and api_secret are required")
        plaintext = json.dumps(
            {"api_key": api_key, "api_secret": api_secret},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
        ciphertext = self._fernet.encrypt(plaintext)
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO funding_credentials (venue, ciphertext, active, updated_at)
                VALUES (?, ?, 1, ?)
                ON CONFLICT(venue) DO UPDATE SET
                    ciphertext = excluded.ciphertext,
                    active = 1,
                    updated_at = excluded.updated_at
                """,
                (venue, ciphertext, updated_at),
            )
        return CredentialStatus(venue, True, True, updated_at)

    def load(self, venue: str) -> dict[str, str]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT ciphertext, active FROM funding_credentials WHERE venue = ?", (venue,)
            ).fetchone()
        if row is None or not bool(row["active"]):
            raise VaultUnavailable(f"credentials are not active for {venue}")
        try:
            plaintext = self._fernet.decrypt(bytes(row["ciphertext"]))
            payload = json.loads(plaintext)
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VaultUnavailable("credential record cannot be decrypted") from exc
        return {
            "api_key": str(payload["api_key"]),
            "api_secret": str(payload["api_secret"]),
        }

    def status(self, venue: str) -> CredentialStatus:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT active, updated_at FROM funding_credentials WHERE venue = ?", (venue,)
            ).fetchone()
        if row is None:
            return CredentialStatus(venue, False, False, None)
        return CredentialStatus(venue, True, bool(row["active"]), str(row["updated_at"]))

    def disable(self, venue: str) -> CredentialStatus:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE funding_credentials SET active = 0, updated_at = ? WHERE venue = ?",
                (updated_at, venue),
            )
        return self.status(venue)
