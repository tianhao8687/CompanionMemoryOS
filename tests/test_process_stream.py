"""Real app process + local HTTP model fixture. No real model service or paid calls."""

from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from companion_agent.deepseek import DeepSeekConfig
from companion_agent.romance import RomanceSettings
from companion_agent.testing.driver import DriverError, ManagedInstance


def test_stream_errors_retry_cancel_and_all_adapter_calls_are_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[dict[str, Any]] = []
    mode = ["error"]
    started = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            if mode[0] == "error":
                self.send_response(503)
                self.end_headers()
                return
            extraction = "extract candidates" in body["messages"][0]["content"]
            if extraction:
                payload = {
                    "model": "http-fixture",
                    "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
                    "usage": {"total_tokens": 5},
                }
                raw = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()

            def send(delta: dict[str, Any], finish: str | None = None) -> None:
                data = {
                    "model": "http-fixture",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                self.wfile.write(("data: " + json.dumps(data) + "\n\n").encode())
                self.wfile.flush()

            try:
                send({"role": "assistant", "reasoning_content": "private-test-reasoning"})
                send({"content": "测试回复"})
                started.set()
                if mode[0] == "slow":
                    for _ in range(25):
                        time.sleep(0.05)
                        send({"content": "。"})
                send({}, "stop")
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("DEEPSEEK_BASE_URL", endpoint)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "synthetic-fixture-key")
    settings = RomanceSettings(
        storage_consent=True,
        model_consent=True,
        model_mode="api",
        deepseek=DeepSeekConfig(base_url=endpoint, model="deepseek-chat"),
    )
    channel = os.environ.get("COMPANION_TEST_BROWSER_CHANNEL")
    instance = ManagedInstance(
        Path(".agent-tests") if channel else tmp_path,
        allow_live=True,
        settings=settings.model_dump(mode="json"),
    )
    try:
        client = instance.start()
        conversation = client.new_session()
        with pytest.raises(DriverError, match="stream did not complete"):
            client.send_message(conversation, "你好", stream=True, request_id="retry")
        assert [m["role"] for m in client.read_history(conversation)] == ["user"]
        mode[0] = "normal"
        result = client.send_message(conversation, "你好", stream=True, request_id="retry")
        assert not result["reused"] and len(client.read_history(conversation)) == 2
        assert "private-test-reasoning" not in json.dumps(result)
        assert "synthetic-fixture-key" not in json.dumps(result)
        same = client.send_message(conversation, "你好", stream=True, request_id="retry")
        assert same["reused"] and len(requests) == 2
        mode[0] = "slow"
        started.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(
                client.send_message, conversation, "这轮取消", stream=True, request_id="cancel"
            )
            assert started.wait(timeout=10)
            assert client.request("POST", "/api/automation/cancel/cancel", {})["cancelled"]
            with pytest.raises(DriverError, match="stream did not complete"):
                pending.result(timeout=10)
        assert [m["role"] for m in client.read_history(conversation)] == [
            "user",
            "assistant",
            "user",
        ]
        traces = client.request(
            "GET", f"/api/testing/traces?conversation_id={conversation}&request_id=cancel"
        )
        assert traces[0]["status"] == "failed"
        mode[0] = "normal"
        settings.cognition.model_extraction = True
        client.request("PUT", "/api/settings", {"settings": settings.model_dump(mode="json")})
        output = client.send_message(conversation, "我喜欢薄荷。", stream=True)
        assert {call["source"] for call in output["trace"]["calls"]} == {"chat", "extraction"}
        assert client.connect()["accounting"]["calls"] == len(requests) == 5
        if channel:
            from companion_agent.testing.web_smoke import check_failure_controls

            evidence = check_failure_controls(
                instance, lambda value: mode.__setitem__(0, value), channel=channel
            )
            evidence_file = instance.directory / "web-faults.json"
            evidence_file.write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            output_path = Path(".agent-tests/verification/web-faults.json")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(
                    {"status": evidence["status"], "evidence": str(evidence_file)}, indent=2
                ),
                encoding="utf-8",
            )
    finally:
        instance.stop()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
