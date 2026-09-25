"""Android Keystore bridge. Secrets never enter settings JSON or SQLite backups."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from companion_agent.credentials import CredentialStore, CredentialStoreError


class AndroidCredentialStore(CredentialStore):
    def __init__(self, data_dir: Path, context: Any) -> None:
        super().__init__(data_dir)
        self.available = True
        java = importlib.import_module("java")
        self.bridge = java.jclass("com.xinyu.xinyu_flutter.DeviceCredentials")(context)

    def load(self, endpoint: str) -> str | None:
        try:
            result = self.bridge.load(self.target(endpoint))
            return str(result) if result is not None else None
        except Exception:
            raise CredentialStoreError("credential_store_read_failed") from None

    def save(self, endpoint: str, value: str) -> None:
        if (
            not 0 < len(value) <= 512
            or not value.isascii()
            or any(not character.isprintable() or character.isspace() for character in value)
        ):
            raise CredentialStoreError("credential_store_invalid_value")
        try:
            self.bridge.save(self.target(endpoint), value)
        except Exception:
            raise CredentialStoreError("credential_store_write_failed") from None

    def delete(self, endpoint: str) -> None:
        try:
            self.bridge.delete(self.target(endpoint))
        except Exception:
            raise CredentialStoreError("credential_store_delete_failed") from None
