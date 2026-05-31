from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken

from rhythia.config import DATA_DIR, TOKEN_ENCRYPTION_KEY_FILE, load_env_file


class SessionTokenCipher:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    @classmethod
    def load(cls, path=TOKEN_ENCRYPTION_KEY_FILE) -> SessionTokenCipher:
        """Key from TOKEN_ENCRYPTION_KEY in .env, else data/.link_key (auto-created)."""
        load_env_file()
        env_key = os.environ.get("TOKEN_ENCRYPTION_KEY", "").strip()
        if env_key:
            return cls(env_key.encode("ascii"))

        if not path.is_file():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            path.write_bytes(key)
            path.chmod(0o600)
        return cls(path.read_bytes())

    def encrypt(self, token: str) -> str:
        return self._fernet.encrypt(token.encode("utf-8")).decode("ascii")

    def decrypt(self, encrypted: str) -> str:
        try:
            return self._fernet.decrypt(encrypted.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Invalid token (encryption key changed?)") from exc
