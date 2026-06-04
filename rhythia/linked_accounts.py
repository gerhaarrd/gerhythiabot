"""Discord ↔ Rhythia account links."""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rhythia.config import LINKED_ACCOUNTS_DB_PATH


@dataclass(frozen=True, slots=True)
class LinkedAccount:
    discord_id: int
    rhythia_user_id: int | None
    rhythia_username: str
    linked_at: str


@dataclass(frozen=True, slots=True)
class PendingLink:
    discord_id: int
    rhythia_user_id: int
    rhythia_username: str
    code: str
    created_at: str
    expires_at: str


class LinkedAccountStore:
    def __init__(
        self,
        db_path: Path = LINKED_ACCOUNTS_DB_PATH,
    ) -> None:
        self._db_path = db_path
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
                linked_at TEXT NOT NULL
            )
            """
        )
        # No token storage required; keep schema minimal.
        # Index on rhythia_user_id for potential future lookups
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_links_rhythia_user_id ON links (rhythia_user_id)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_links (
                discord_id TEXT PRIMARY KEY,
                rhythia_user_id INTEGER NOT NULL,
                rhythia_username TEXT NOT NULL,
                code TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )

    def _migrate_token_optional(self) -> None:
        # Token storage removed; no migration needed.
        return

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(
        self,
        discord_id: int,
        *,
        rhythia_user_id: int,
        rhythia_username: str,
    ) -> LinkedAccount:
        linked_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._get_conn().execute(
                """
                INSERT INTO links (discord_id, rhythia_user_id, rhythia_username, linked_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET
                    rhythia_user_id = excluded.rhythia_user_id,
                    rhythia_username = excluded.rhythia_username,
                    linked_at = excluded.linked_at
                """,
                (str(discord_id), rhythia_user_id, rhythia_username, linked_at),
            )
        return LinkedAccount(
            discord_id=discord_id,
            rhythia_user_id=rhythia_user_id,
            rhythia_username=rhythia_username,
            linked_at=linked_at,
        )

    def save_pending(
        self,
        discord_id: int,
        *,
        rhythia_user_id: int,
        rhythia_username: str,
        code: str,
        ttl_minutes: int = 15,
    ) -> PendingLink:
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        expires_at = (now + timedelta(minutes=ttl_minutes)).isoformat()
        with self._lock:
            self._get_conn().execute(
                """
                INSERT INTO pending_links (discord_id, rhythia_user_id, rhythia_username, code, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(discord_id) DO UPDATE SET
                    rhythia_user_id = excluded.rhythia_user_id,
                    rhythia_username = excluded.rhythia_username,
                    code = excluded.code,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (
                    str(discord_id),
                    rhythia_user_id,
                    rhythia_username,
                    code,
                    created_at,
                    expires_at,
                ),
            )
        return PendingLink(
            discord_id=discord_id,
            rhythia_user_id=rhythia_user_id,
            rhythia_username=rhythia_username,
            code=code,
            created_at=created_at,
            expires_at=expires_at,
        )

    def get_pending(self, discord_id: int) -> PendingLink | None:
        row = self._get_conn().execute(
            """
            SELECT rhythia_user_id, rhythia_username, code, created_at, expires_at
            FROM pending_links
            WHERE discord_id = ?
            """,
            (str(discord_id),),
        ).fetchone()
        if row is None:
            return None

        expires_at = datetime.fromisoformat(row["expires_at"])
        if expires_at <= datetime.now(timezone.utc):
            self.delete_pending(discord_id)
            return None

        return PendingLink(
            discord_id=discord_id,
            rhythia_user_id=row["rhythia_user_id"],
            rhythia_username=row["rhythia_username"],
            code=row["code"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
        )

    def delete_pending(self, discord_id: int) -> bool:
        with self._lock:
            cursor = self._get_conn().execute(
                "DELETE FROM pending_links WHERE discord_id = ?",
                (str(discord_id),),
            )
            return cursor.rowcount > 0

    def cleanup_expired_pending(self) -> int:
        with self._lock:
            cursor = self._get_conn().execute(
                "DELETE FROM pending_links WHERE expires_at <= ?",
                (datetime.now(timezone.utc).isoformat(),),
            )
            return cursor.rowcount

    def get_account(self, discord_id: int) -> LinkedAccount | None:
        row = self._get_conn().execute(
            "SELECT rhythia_user_id, rhythia_username, linked_at FROM links WHERE discord_id = ?",
            (str(discord_id),),
        ).fetchone()
        if row is None:
            return None

        return LinkedAccount(
            discord_id=discord_id,
            rhythia_user_id=row["rhythia_user_id"],
            rhythia_username=row["rhythia_username"],
            linked_at=row["linked_at"],
        )

    def delete(self, discord_id: int) -> bool:
        with self._lock:
            cursor = self._get_conn().execute(
                "DELETE FROM links WHERE discord_id = ?",
                (str(discord_id),),
            )
            if cursor.rowcount > 0:
                return True
            return False
