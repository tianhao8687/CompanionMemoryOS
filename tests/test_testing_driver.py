from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from companion_agent.testing.control import TestControl as DiagnosticControl
from companion_agent.testing.driver import Client, DriverError, ManagedInstance


@pytest.mark.skipif(os.name != "nt", reason="Windows transient file sharing locks")
def test_transient_accounting_replace_preserves_charges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = ManagedInstance(tmp_path)
    try:
        control = DiagnosticControl(instance.directory, instance.token)
        control.accounting.update(calls=3, turns=2, live_calls=3)
        original = Path.replace
        attempts = 0

        def locked_once(source: Path, target: Path) -> Path:
            nonlocal attempts
            if target == control.accounting_path:
                attempts += 1
                if attempts == 1:
                    raise PermissionError("synthetic file sharing lock")
            return original(source, target)

        monkeypatch.setattr(Path, "replace", locked_once)
        control.save_accounting()
        assert attempts == 2
        assert json.loads(control.accounting_path.read_text()) == control.accounting
        assert (
            DiagnosticControl(instance.directory, instance.token).accounting == control.accounting
        )
    finally:
        instance.cleanup()


def test_real_http_process_handshake_final_trace_restart_and_idempotency(tmp_path: Path) -> None:
    instance = ManagedInstance(tmp_path, max_calls=8)
    try:
        client = instance.start()
        identity = client.identity
        assert identity["synthetic_data"] and identity["model_mode"] == "offline"
        assert identity["process_management"] and "restart" in identity["capabilities"]
        assert instance.process and identity["pid"] == instance.process.pid
        with pytest.raises(DriverError, match="HTTP 403"):
            Client(client.url, "wrong-instance-token").connect()
        unauthenticated = Client(client.url, instance.token)
        with pytest.raises(DriverError, match="HTTP 401"):
            unauthenticated.request("GET", "/api/testing/discover")
        attached = unauthenticated.connect()
        assert not attached["process_management"] and "restart" not in attached["capabilities"]
        conversation = client.new_session()
        result = client.send_message(
            conversation, "我不喜欢被分析。", stream=True, request_id="stable"
        )
        trace = result["trace"]
        request = trace["calls"][0]["request"]
        assert "用户明确要求使用工具" in request["messages"][0]["content"]
        assert request["tools"]  # Actual AgentLoop request, not prepare() alone.
        assert trace["prepared"]["preferences"][0]["dimension"] == "psychological_analysis"
        reused = client.send_message(conversation, "我不喜欢被分析。", request_id="stable")
        assert reused["reused"] and reused["assistant"]["id"] == result["assistant"]["id"]
        assert not reused["trace"]["calls"]
        assert len(client.read_history(conversation)) == 2
        before = client.read_state(conversation)
        database_path = next((instance.directory / "data").glob("*.db"))
        with sqlite3.connect(database_path) as database:
            fingerprint_before = "\n".join(database.iterdump())
        assert client.read_state(conversation) == before
        with sqlite3.connect(database_path) as database:
            assert "\n".join(database.iterdump()) == fingerprint_before
        client = instance.restart()
        assert client.identity["instance_id"] != identity["instance_id"]
        assert client.identity["run_id"] == identity["run_id"]
        assert client.identity["accounting"]["calls"] == 1
        second = client.new_session()
        reply = client.send_message(second, "今天阳光很好。")
        assert "避免主动解读" in json.dumps(reply["trace"]["calls"], ensure_ascii=False)
        record = next(r for r in client.read_state(second)["memories"] if r["status"] == "active")
        client.forget_memory(record["id"])
        with pytest.raises(DriverError, match="HTTP 404"):
            client.inspect_trace(reply["trace_id"])
        for path in ("/api/automation/config", "/api/channels"):
            with pytest.raises(DriverError, match="HTTP 403"):
                client.request("PUT", path, {})
    finally:
        instance.stop()
    assert instance.process and instance.process.poll() is not None


def test_call_budget_survives_restart_and_does_not_fallback(tmp_path: Path) -> None:
    instance = ManagedInstance(tmp_path, max_calls=1, max_turns=4)
    try:
        client = instance.start()
        conversation = client.new_session()
        client.send_message(conversation, "你好。")
        client = instance.restart()
        with pytest.raises(DriverError, match="HTTP 502"):
            client.send_message(conversation, "第二轮。")
        history = client.read_history(conversation)
        assert [turn["role"] for turn in history] == ["user", "assistant", "user"]
        assert client.connect()["accounting"]["calls"] == 1
        settings = client.request("GET", "/api/bootstrap")["settings"]
        settings["model_mode"] = "api"
        with pytest.raises(DriverError, match="HTTP 403"):
            client.request("PUT", "/api/settings", {"settings": settings})
    finally:
        instance.stop()


def test_no_secret_or_reasoning_in_diagnostics(tmp_path: Path) -> None:
    instance = ManagedInstance(tmp_path)
    control = DiagnosticControl(instance.directory, instance.token)
    control.secrets.append("synthetic-provider-secret")
    cleaned = control.clean(
        {
            "messages": [
                {"role": "assistant", "reasoning_content": "private text", "content": "visible"}
            ],
            "api_key": "synthetic-provider-secret",
            "authorization": "Bearer synthetic-provider-secret",
            "tool_result": "contains synthetic-provider-secret",
            "token": instance.token,
        }
    )
    assert "private text" not in json.dumps(cleaned)
    assert "synthetic-provider-secret" not in json.dumps(cleaned)
    assert instance.token not in json.dumps(cleaned)
    assert "visible" in json.dumps(cleaned)
    control.marker["expires_at"] = 0
    assert not control.valid()
    instance.cleanup()


def test_cleanup_refuses_linked_tree_and_unowned_directory(tmp_path: Path) -> None:
    instance = ManagedInstance(tmp_path / "runs")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    link = instance.directory / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("host does not permit symlink creation")
    with pytest.raises(DriverError, match="linked"):
        instance.cleanup()
    assert sentinel.read_text(encoding="utf-8") == "keep"
    link.unlink()
    instance.cleanup()
    with pytest.raises(FileNotFoundError):
        DiagnosticControl(outside, "a" * 32)


def test_real_process_context_variants_are_disclosed(tmp_path: Path) -> None:
    # Fresh equivalent data for each variant; the runner never reuses a previous variant's DB.
    full = ManagedInstance(tmp_path)
    other = ManagedInstance(tmp_path, variant="no_examples")
    assert full.directory != other.directory
    try:
        client = other.start()
        assert client.identity["variant"] == "no_examples"
        response = client.send_message(client.new_session(), "你好！")
        assert response["trace"]["prepared"]["selected_examples"] == []
        assert response["trace"]["calls"][0]["request"]["messages"]
    finally:
        full.cleanup()
        other.cleanup()


def test_export_ttl_only_cleans_owned_closed_runs(tmp_path: Path) -> None:
    instance = ManagedInstance(tmp_path)
    (instance.directory / "results.json").write_text('{"status":"failed"}', encoding="utf-8")
    instance.marker["delete_after"] = 0
    (instance.directory / "run.json").write_text(json.dumps(instance.marker), encoding="utf-8")
    unknown = tmp_path / "ordinary"
    unknown.mkdir()
    (unknown / "keep.txt").write_text("not a test artifact", encoding="utf-8")
    instance.stop()
    new = ManagedInstance(tmp_path)
    assert not instance.directory.exists()
    assert (unknown / "keep.txt").exists()
    assert '"status": "failed"' in (tmp_path / "retention-receipts.jsonl").read_text(
        encoding="utf-8"
    )
    new.cleanup()
