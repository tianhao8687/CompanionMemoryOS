from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from companion_agent import app
from companion_agent.credentials import CredentialStore, CredentialStoreError
from companion_agent.romance import RomanceSettings


class MemoryCredentials(CredentialStore):
    values: ClassVar[dict[str, str]] = {}
    fail: ClassVar[bool] = False

    def __init__(self, data_dir: Path, *, enabled: bool = True) -> None:
        super().__init__(data_dir, enabled=enabled)
        self.available = enabled

    def load(self, endpoint: str) -> str | None:
        if not self.available:
            return None
        if self.fail:
            raise CredentialStoreError("synthetic_store_failure")
        return self.values.get(self.target(endpoint))

    def save(self, endpoint: str, value: str) -> None:
        if not self.available or self.fail:
            raise CredentialStoreError("synthetic_store_failure")
        self.values[self.target(endpoint)] = value

    def delete(self, endpoint: str) -> None:
        if self.fail:
            raise CredentialStoreError("synthetic_store_failure")
        self.values.pop(self.target(endpoint), None)


@pytest.fixture
def credentials(monkeypatch: pytest.MonkeyPatch) -> type[MemoryCredentials]:
    MemoryCredentials.values = {}
    MemoryCredentials.fail = False
    monkeypatch.setattr(app, "CredentialStore", MemoryCredentials)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    return MemoryCredentials


def client_for(path: Path) -> TestClient:
    client = TestClient(
        app.create_app(path),
        base_url="http://127.0.0.1",
        headers={"X-Companion-Client": "local-web", "Origin": "http://127.0.0.1"},
    )
    assert client.get("/").status_code == 200
    return client


def test_remembered_key_survives_restart_without_database_or_api_disclosure(
    tmp_path: Path, credentials: type[MemoryCredentials]
) -> None:
    client = client_for(tmp_path)
    settings = RomanceSettings(model_mode="api").model_dump(mode="json")
    secret = "synthetic-remembered-key"
    result = client.put(
        "/api/settings",
        json={"settings": settings, "api_key": secret, "remember_api_key": True},
    )
    assert result.status_code == 200
    assert result.json()["key_persisted"]
    assert result.json()["key_source"] == "credential_store"
    restarted = client_for(tmp_path)
    state = restarted.get("/api/bootstrap")
    assert state.json()["key_configured"] and state.json()["key_persisted"]
    assert restarted.app.state.host.api_key == secret  # type: ignore[union-attr]
    assert secret not in result.text + state.text + restarted.get("/api/export").text
    assert secret.encode() not in (tmp_path / "companion-memoryos.db").read_bytes()
    # Existing programmatic updates omit the option and preserve the credential.
    settings["user_name"] = "小雨"
    assert restarted.put("/api/settings", json={"settings": settings}).json()["key_persisted"]
    assert client_for(tmp_path).get("/api/bootstrap").json()["key_persisted"]


@pytest.mark.parametrize("clear", [False, True])
def test_opt_out_and_clear_remove_saved_key(
    tmp_path: Path, credentials: type[MemoryCredentials], clear: bool
) -> None:
    client = client_for(tmp_path)
    settings = RomanceSettings().model_dump(mode="json")
    secret = "synthetic-clear-key"
    assert (
        client.put(
            "/api/settings",
            json={"settings": settings, "api_key": secret, "remember_api_key": True},
        ).status_code
        == 200
    )
    payload = (
        {"settings": settings, "clear_api_key": True}
        if clear
        else {"settings": settings, "remember_api_key": False}
    )
    result = client.put("/api/settings", json=payload).json()
    assert result["key_configured"] == (not clear)
    assert not result["key_persisted"] and not credentials.values
    assert not client_for(tmp_path).get("/api/bootstrap").json()["key_configured"]


def test_persistent_credentials_stay_bound_to_installation_and_endpoint(
    tmp_path: Path, credentials: type[MemoryCredentials]
) -> None:
    client = client_for(tmp_path / "first")
    settings = RomanceSettings().model_dump(mode="json")
    secret = "synthetic-official-key"
    assert (
        client.put(
            "/api/settings",
            json={"settings": settings, "api_key": secret, "remember_api_key": True},
        ).status_code
        == 200
    )
    assert not client_for(tmp_path / "second").get("/api/bootstrap").json()["key_configured"]
    settings["deepseek"]["base_url"] = "https://other-provider.example/v1"
    assert client.put("/api/settings", json={"settings": settings}).status_code == 400
    changed = client.put(
        "/api/settings", json={"settings": settings, "api_key": "synthetic-other-key"}
    )
    assert changed.status_code == 200 and not changed.json()["key_persisted"]
    assert not client_for(tmp_path / "first").get("/api/bootstrap").json()["key_configured"]


def test_vault_failure_is_visible_and_does_not_report_success(
    tmp_path: Path, credentials: type[MemoryCredentials]
) -> None:
    client = client_for(tmp_path)
    original = client.get("/api/bootstrap").json()["settings"]
    credentials.fail = True
    secret = "synthetic-failed-key"
    failed = client.put(
        "/api/settings",
        json={
            "settings": {**original, "user_name": "changed"},
            "api_key": secret,
            "remember_api_key": True,
        },
    )
    assert failed.status_code == 503 and secret not in failed.text
    assert client.get("/api/bootstrap").json()["settings"] == original
    restarted = client_for(tmp_path)
    state = restarted.get("/api/bootstrap").json()
    assert state["credential_store_error"] and not state["key_configured"]


def test_disabled_store_never_reads_system_credentials(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path, enabled=False)
    assert not store.available and store.load("https://api.deepseek.com") is None
    with pytest.raises(CredentialStoreError, match="unavailable"):
        store.save("https://api.deepseek.com", "synthetic-key")


def test_windows_vault_round_trip_and_delete(tmp_path: Path) -> None:
    store = CredentialStore(tmp_path)
    if not store.available:
        pytest.skip("Windows Credential Manager requires Windows")
    endpoint = "https://synthetic-credential-test.invalid"
    secret = "synthetic-key-for-windows-vault-test"
    try:
        assert store.load(endpoint) is None
        store.save(endpoint, secret)
        assert CredentialStore(tmp_path).load(endpoint) == secret
        assert store.load("https://other-synthetic-test.invalid") is None
        store.delete(endpoint)
        assert store.load(endpoint) is None
    finally:
        store.delete(endpoint)
