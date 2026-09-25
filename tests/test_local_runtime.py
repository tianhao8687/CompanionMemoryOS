"""Native runtime acceptance with synthetic data, no device or real model calls."""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from threading import Thread
from typing import Any

import httpx
import pytest

from companion_agent.local_runtime import LocalRuntime


def start_process(directory: Path) -> tuple[subprocess.Popen[str], httpx.Client]:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DEEPSEEK_", "COMPANION_", "PYTHONPATH", "PYTHONHOME"))
    }
    executable = env.get("XINYU_TEST_ENGINE")
    command = (
        [executable] if executable else [sys.executable, "-m", "companion_agent.local_runtime"]
    )
    process = subprocess.Popen(
        [*command, "--data-dir", str(directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=directory.parent if executable else None,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    assert process.stdout is not None
    lines: queue.Queue[str] = queue.Queue()
    Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
    try:
        result = json.loads(lines.get(timeout=40))
        assert result.get("protocol") == 1, "runtime did not become ready"
        client = httpx.Client(
            base_url=result["endpoint"],
            headers={"X-Xinyu-Token": result["token"], "X-Companion-Client": "local-web"},
            timeout=30,
            trust_env=False,
        )
        assert client.get("/").status_code == 200
        return process, client
    except BaseException:
        process.kill()
        process.wait(timeout=5)
        raise


def stop_process(process: subprocess.Popen[str], client: httpx.Client) -> None:
    client.close()
    if process.stdin is not None:
        process.stdin.close()
    try:
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def request(client: httpx.Client, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    response = client.request(method, path, **kwargs)
    assert response.is_success, (response.status_code, response.text[:250])
    return response.json()  # type: ignore[no-any-return]


def test_native_runtime_restart_idempotency_backup_restore_and_eof(tmp_path: Path) -> None:
    directory = tmp_path / "native-data"
    process, client = start_process(directory)
    try:
        assert httpx.get(str(client.base_url), trust_env=False).status_code == 401
        assert client.get("/", headers={"X-Xinyu-Token": "wrong"}).status_code == 401
        boot = request(client, "GET", "/api/bootstrap")
        values = boot["settings"] | {"storage_consent": True, "model_consent": True}
        request(client, "PUT", "/api/settings", json={"settings": values})
        conversation = boot["conversations"][0]["id"]
        message = {
            "conversation_id": conversation,
            "request_id": "native-synthetic-1",
            "content": "我喜欢喝热茶。",
        }
        first = request(client, "POST", "/api/chat", json=message)
        replay = request(client, "POST", "/api/chat", json=message)
        assert first["user"]["id"] == replay["user"]["id"]
        assert first["assistant"]["id"] == replay["assistant"]["id"]
        backup = client.get("/api/local/backup")
        assert backup.status_code == 200
        assert backup.content.startswith(b"SQLite format 3")
        request(client, "PUT", "/api/settings", json={"settings": values | {"user_name": "备份后"}})
        assert client.post("/api/local/restore", content=b"invalid").status_code == 422
        invalid_settings = tmp_path / "invalid-settings.sqlite"
        invalid_settings.write_bytes(backup.content)
        with closing(sqlite3.connect(invalid_settings)) as db, db:
            db.execute("UPDATE romance_settings SET data_json='not json' WHERE id=1")
        assert (
            client.post("/api/local/restore", content=invalid_settings.read_bytes()).status_code
            == 422
        )
        assert request(client, "GET", "/api/bootstrap")["settings"]["user_name"] == "备份后"
        assert client.put("/api/channels", json={}).status_code == 403
        restored = request(client, "POST", "/api/local/restore", content=backup.content)
        assert restored["restart_required"]
        assert client.post("/api/chat", json=message).status_code == 409
    finally:
        stop_process(process, client)
    process, client = start_process(directory)
    try:
        boot = request(client, "GET", "/api/bootstrap")
        assert boot["settings"]["user_name"] == values["user_name"]
        history = request(client, "GET", f"/api/conversations/{conversation}/messages")
        assert [row["id"] for row in history["messages"]] == [
            first["user"]["id"],
            first["assistant"]["id"],
        ]
        assert len(list((directory / "recovery").glob("*.sqlite"))) == 1
        assert not (directory / "restore-pending.sqlite").exists()
    finally:
        stop_process(process, client)


def test_two_instances_cannot_open_the_same_data_and_stop_releases_lease(tmp_path: Path) -> None:
    first = LocalRuntime(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="另一个"):
            LocalRuntime(tmp_path)
    finally:
        first.stop()
    second = LocalRuntime(tmp_path)
    second.stop()
