from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ENV_FILE = PROJECT_ROOT / ".env"
LINKED_ACCOUNTS_DB_PATH = DATA_DIR / "links.db"
TOKEN_ENCRYPTION_KEY_FILE = DATA_DIR / ".link_key"

RHYTHIA_OAUTH_BASE_URL = os.environ.get(
    "RHYTHIA_OAUTH_BASE_URL", "https://pfkajngbllcbdzoylrvp.supabase.co"
).rstrip("/")

_dotenv_loaded = False


def load_env_file() -> None:
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    from dotenv import load_dotenv

    if ENV_FILE.is_file():
        load_dotenv(ENV_FILE)
        logger.info("Loaded %s", ENV_FILE.name)
    else:
        logger.warning(
            "No %s found — set DISCORD_TOKEN (and optionally TOKEN_ENCRYPTION_KEY) "
            "in environment variables.",
            ENV_FILE.name,
        )
    _dotenv_loaded = True


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    guild_id: int | None = None
    sync_commands: bool = True

    @classmethod
    def for_bot(cls) -> Settings:
        load_env_file()
        discord_token = os.environ.get("DISCORD_TOKEN", "").strip()
        if not discord_token:
            raise ValueError("Set DISCORD_TOKEN in your .env file.")

        guild_raw = os.environ.get("DISCORD_GUILD_ID", "").strip()
        guild_id = int(guild_raw) if guild_raw else None

        sync_commands = _env_flag("SYNC_COMMANDS", default=True) and not _env_flag(
            "SKIP_COMMAND_SYNC"
        )

        return cls(
            discord_token=discord_token,
            guild_id=guild_id,
            sync_commands=sync_commands,
        )
