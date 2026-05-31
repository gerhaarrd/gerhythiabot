"""Discord ↔ Rhythia account links (encrypted session tokens)."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from rhythia.config import LINKED_ACCOUNTS_DB_PATH
from rhythia.oauth_login import session_token_is_expired
from rhythia.token_encryption import SessionTokenCipher


class AccountNotLinkedError(Exception):
    """Discord user has not linked a Rhythia account yet."""


@dataclass(frozen=True, slots=True)
class LinkedAccount:
    discord_id: int
    rhythia_user_id: int | None
    rhythia_username: str
    linked_at: str


class LinkedAccountStore:
    def __init__(
        self,
        db_path: Path = LINKED_ACCOUNTS_DB_PATH,
        cipher: SessionTokenCipher | None = None,
    ) -> None:
        self._db_path = db_path
        self._cipher = cipher or SessionTokenCipher.load()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    # ------------------------------------------------------------------
    # Connection management — single persistent connection, WAL mode
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
                isolation_level=None,  # autocommit; we manage transactions manually
            )
            conn.row_factory = sqlite3.Row
            # WAL: readers never block writers and vice-versa
            conn.execute("PRAGMA journal_mode=WAL")
            # NORMAL is safe with WAL and much faster than FULL
            conn.execute("PRAGMA synchronous=NORMAL")
            # Keep 4 MB of B-tree pages in RAM
            conn.execute("PRAGMA cache_size=-4096")
            # Use RAM for temporary tables/sorting
            conn.execute("PRAGMA temp_store=MEMORY")
            self._conn = conn
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                discord_id TEXT PRIMARY KEY,
                rhythia_user_id INTEGER,
                rhythia_username TEXT NOT NULL,
                token_encrypted TEXT NOT NULL,
                linked_at TEXT NOT NULL
            )
            """
        )
        # Index on rhythia_user_id for potential future lookups
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_links_rhythia_user_id ON links (rhythia_user_id)"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(
        self,
        discord_id: int,
        *,
        session_token: str,
        rhythia_user_id: int | None,
        rhythia_username: str,
    ) -> LinkedAccount:
        encrypted = self._cipher.encrypt(session_token.strip())
        linked_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._get_conn().execute(
                """
                INSERT INTO links (discord_id, rhythia_user_id, rhythia_username, token_encrypted, linked_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET
                    rhythia_user_id = excluded.rhythia_user_id,
                    rhythia_username = excluded.rhythia_username,
                    token_encrypted = excluded.token_encrypted,
                    linked_at = excluded.linked_at
                """,
                (str(discord_id), rhythia_user_id, rhythia_username, encrypted, linked_at),
            )
            # Invalidate cached token for this user after re-link
            self._cached_token.cache_clear()
        return LinkedAccount(
            discord_id=discord_id,
            rhythia_user_id=rhythia_user_id,
            rhythia_username=rhythia_username,
            linked_at=linked_at,
        )

    def get_account(self, discord_id: int) -> LinkedAccount | None:
        row = self._get_conn().execute(
            "SELECT rhythia_user_id, rhythia_username, linked_at, token_encrypted FROM links WHERE discord_id = ?",
            (str(discord_id),),
        ).fetchone()
        if row is None:
            return None

        try:
            token = self._cipher.decrypt(row["token_encrypted"])
        except ValueError:
            return None

        if session_token_is_expired(token):
            self.delete(discord_id)
            return None

        return LinkedAccount(
            discord_id=discord_id,
            rhythia_user_id=row["rhythia_user_id"],
            rhythia_username=row["rhythia_username"],
            linked_at=row["linked_at"],
        )

    def get_session_token(self, discord_id: int) -> str:
        return self._cached_token(discord_id)

    def cleanup_expired_tokens(self) -> int:
        with self._lock:
            cursor = self._get_conn().execute(
                "SELECT discord_id, token_encrypted FROM links"
            )
            deleted = 0
            for row in cursor:
                try:
                    token = self._cipher.decrypt(row["token_encrypted"])
                except ValueError:
                    continue
                if session_token_is_expired(token):
                    self._get_conn().execute(
                        "DELETE FROM links WHERE discord_id = ?",
                        (row["discord_id"],),
                    )
                    deleted += 1
            if deleted:
                self._cached_token.cache_clear()
            return deleted

    def delete(self, discord_id: int) -> bool:
        with self._lock:
            cursor = self._get_conn().execute(
                "DELETE FROM links WHERE discord_id = ?",
                (str(discord_id),),
            )
            if cursor.rowcount > 0:
                self._cached_token.cache_clear()
                return True
            return False

    # ------------------------------------------------------------------
    # Internal — LRU cache for decrypted tokens (avoids Fernet overhead
    # on repeated commands from the same user in a short window)
    # ------------------------------------------------------------------

    @lru_cache(maxsize=256)
    def _cached_token(self, discord_id: int) -> str:
        row = self._get_conn().execute(
            "SELECT token_encrypted FROM links WHERE discord_id = ?",
            (str(discord_id),),
        ).fetchone()
        if row is None:
            raise AccountNotLinkedError(
                "You haven't linked your account yet. Use `/rhythia link` to connect."
            )

        token = self._cipher.decrypt(row["token_encrypted"])
        if session_token_is_expired(token):
            with self._lock:
                self._get_conn().execute(
                    "DELETE FROM links WHERE discord_id = ?",
                    (str(discord_id),),
                )
                self._cached_token.cache_clear()
            raise AccountNotLinkedError(
                "Your session token expired. Use `/rhythia link` again."
            )
        return token
