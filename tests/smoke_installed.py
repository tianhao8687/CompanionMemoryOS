"""Run with a clean installed interpreter, data directory and pre-created port config."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path
from threading import Event
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import companion_memoryos
from companion_memoryos.config import load_config


def main() -> None:
    data_dir, config_path = (Path(item).resolve() for item in sys.argv[1:])
    assert Path(companion_memoryos.__file__).is_relative_to(Path(sys.prefix))
    assert version("companion-memoryos") == "0.7.5"
    cli = Path(sys.executable).with_name("companion-memoryos")
    prefix = [str(cli), "--data-dir", str(data_dir), "--config", str(config_path)]
    initialized = subprocess.run(
        [*prefix, "init"],
        check=True,
        capture_output=True,
        text=True,
    )
    receipt = json.loads(initialized.stdout)
    token = Path(receipt["token_file"]).read_text().strip()
    config = load_config(config_path)
    base_url = f"http://127.0.0.1:{config.server.port}"
    server = subprocess.Popen(
        [*prefix, "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    def call(path, body=None, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(
            base_url + path,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    try:
        deadline = time.monotonic() + 15
        while True:
            try:
                assert call("/api/health", authenticated=False)["status"] == "ok"
                break
            except (URLError, ConnectionError):
                if server.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("installed CLI server did not become ready") from None
                Event().wait(0.05)
        try:
            call("/api/v1/config", authenticated=False)
        except HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("protected endpoint accepted an unauthenticated request")
        scope = {"companion_id": "ai", "relationship_id": "rel", "conversation_id": "chat"}
        body = {
            "user_id": "user",
            "scope": scope,
            "content": "我家猫叫团子，也叫小团",
            "idempotency_key": "installed-smoke",
            "consent": "granted",
            "calendar_timezone": "Asia/Singapore",
        }
        stored = call("/api/v1/turns/process", body)
        assert stored["interpretation_status"] == "not_configured"
        turn_id = stored["storage"]["turn"]["id"]
        applied = call(
            f"/api/v1/turns/{turn_id}/interpretation",
            {
                "user_id": "user",
                "scope": scope,
                "model_fingerprint": "installed-smoke-fixture",
                "idempotency_key": "installed-interpretation",
                "model_output": {
                    "topics": ["团子"],
                    "entities": [
                        {"ref": "cat", "kind": "pet", "name": "团子", "aliases": ["小团"]}
                    ],
                    "episode_hint": {"action": "new", "title": "认识团子"},
                },
            },
        )
        assert applied["entity_resolutions"][0]["status"] == "new"
        assert call("/api/v1/turns/process", body)["interpretation_status"] == "cached"
        recall = call("/api/v1/recall", {"user_id": "user", "scope": scope, "query": "团子"})
        assert any(item["turn"]["id"] == turn_id for item in recall["turn_fallback"])
        episode_id = applied["episode_id"]
        detached = call(
            f"/api/v1/episodes/{episode_id}/detach",
            {
                "user_id": "user",
                "scope": scope,
                "turn_id": turn_id,
            },
        )
        assert detached["status"] == "empty"
        local = call(
            "/api/v1/turns/process",
            {
                **body,
                "content": "先听我说",
                "idempotency_key": "installed-local-rule",
            },
        )
        assert local["interpretation_status"] == "rules_only"
        assert local["response_context"] is None
        with sqlite3.connect(receipt["database"]) as connection:
            assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
            assert schema_version == 8
        print(
            json.dumps(
                {
                    "version": version("companion-memoryos"),
                    "schema": schema_version,
                    "installed_module": companion_memoryos.__file__,
                    "init": "passed",
                    "serve": "passed",
                    "http_process_interpret_recall_detach": "passed",
                }
            )
        )
    finally:
        server.terminate()
        try:
            server.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.communicate(timeout=5)


if __name__ == "__main__":
    main()
