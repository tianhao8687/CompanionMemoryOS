from __future__ import annotations

import contextlib
import secrets
from pathlib import Path

from companion_memoryos.config import CompanionConfig
from companion_memoryos.constants import DEFAULT_ENCODING


class TokenManager:
    def __init__(self, data_dir: Path, config: CompanionConfig) -> None:
        self.path = data_dir.expanduser().resolve() / "api-token"
        self.token_bytes = config.security.token_bytes

    def get_or_create(self) -> str:
        if self.path.exists():
            return self.path.read_text(encoding=DEFAULT_ENCODING).strip()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        token = secrets.token_urlsafe(self.token_bytes)
        self.path.write_text(token, encoding=DEFAULT_ENCODING)
        with contextlib.suppress(OSError):
            self.path.chmod(0o600)
        return token

    def authenticate(self, candidate: str) -> bool:
        expected = self.get_or_create()
        return secrets.compare_digest(candidate, expected)
