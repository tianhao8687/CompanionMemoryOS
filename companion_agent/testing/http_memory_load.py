"""Real isolated HTTP process: concurrent storage reads, chat writes and busy responses.

The application intentionally admits one chat writer. A 409 is counted separately,
never retried or counted as a successful write. Offline replies do not prove QA quality.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

from companion_agent.testing.driver import Client, DriverError, ManagedInstance
from companion_agent.testing.memory_load import latency
from companion_agent.testing.retrieval_benchmark import write_json


def final_evidence(result: dict[str, Any]) -> str:
    for call in reversed(result.get("trace", {}).get("calls", [])):
        for message in call.get("request", {}).get("messages", []):
            content = message.get("content", "")
            marker = "[RELEVANT MEMORY]\n"
            if (
                isinstance(content, str)
                and content.startswith("[APPLICATION CONTEXT]")
                and marker in content
            ):
                payload = json.JSONDecoder().raw_decode(content.split(marker, 1)[1])[0]
                return json.dumps(payload["evidence"], ensure_ascii=False)
    return ""


def main() -> int:
    instance = ManagedInstance(
        Path(".agent-tests"),
        allow_live=False,
        max_turns=100,
        max_calls=200,
        max_output_tokens=4096,
        timeout=600,
    )
    result: dict[str, Any] = {"run_id": instance.run_id, "status": "running", "phases": []}
    write_json(
        instance.directory / "load-protocol.json",
        {
            "readers": [1, 4, 8, 16],
            "pairs_per_reader": 24,
            "writes_per_phase": 8,
            "chat_burst": 8,
            "seed_turns": 16,
            "remote_model_calls": 0,
            "latency_boundary": "Client including trace and persisted-history verification",
            "acceptance": "zero lost acknowledged writes, mismatched evidence or unexpected errors",
            "busy_contract": "one chat writer; HTTP 409 is a rejected request, not throughput",
        },
    )
    print(json.dumps({"event": "started", "run_id": instance.run_id}), flush=True)

    def client() -> Client:
        peer = Client(instance.client.url, instance.token)
        peer.connect(instance.run_id)
        return peer

    def record(phase: dict[str, Any]) -> None:
        result["phases"].append(phase)
        write_json(instance.directory / "load-results.json", result)
        print(json.dumps(phase), flush=True)

    try:
        owner = instance.start()
        settings = owner.request("GET", "/api/bootstrap")["settings"]
        settings["cognition"].update(extract_memory=False, embedding_backend="off")
        owner.request("PUT", "/api/settings", {"settings": settings})
        archive = owner.new_session()
        sources = []
        for index in range(16):
            key, value = f"HT{index:03d}", f"C{(index * 317 + 123) % 997:03d}"
            answer = owner.send_message(archive, f"档案 {key} 的封套保存在 {value} 柜。")
            sources.append({"id": answer["user"]["id"], "key": key, "value": value})
        conversation = owner.new_session()
        for workers in (1, 4, 8, 16):
            peers = [client() for _ in range(workers)]
            barrier = Barrier(workers + 1)

            def reader(peer: Client, gate: Barrier = barrier) -> list[float]:
                durations = []
                gate.wait(timeout=30)
                for _ in range(24):
                    start = time.perf_counter()
                    history = peer.read_history(archive)
                    peer.read_state(conversation)
                    identifiers = {message["id"] for message in history}
                    if not all(source["id"] in identifiers for source in sources):
                        raise AssertionError("acknowledged source missing during concurrent read")
                    durations.append((time.perf_counter() - start) * 1000)
                return durations

            started = time.perf_counter()
            writes = []
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(reader, peer) for peer in peers]
                barrier.wait(timeout=30)
                for index in range(8):
                    source = sources[(index + workers) % len(sources)]
                    start = time.perf_counter()
                    answer = owner.send_message(
                        conversation, f"档案 {source['key']} 的封套保存在什么柜？", stream=True
                    )
                    evidence = final_evidence(answer)
                    writes.append(
                        {
                            "latency_ms": (time.perf_counter() - start) * 1000,
                            "evidence_ok": source["id"] in evidence and source["value"] in evidence,
                            "trace_id": answer["trace_id"],
                            "user_id": answer["user"]["id"],
                        }
                    )
                    write_json(instance.directory / f"http-{workers}-{index}.json", answer)
                reads = [duration for future in futures for duration in future.result()]
            record(
                {
                    "kind": "mixed_http",
                    "readers": workers,
                    "read_pairs": len(reads),
                    "writes": len(writes),
                    "evidence_passed": sum(row["evidence_ok"] for row in writes),
                    "seconds": time.perf_counter() - started,
                    "read_pair_ms": latency(reads),
                    "chat_with_audit_ms": latency([row["latency_ms"] for row in writes]),
                }
            )
            if not all(row["evidence_ok"] for row in writes):
                raise AssertionError("final model input lost the requested source or answer")

        # Observe the application's existing one-writer contract under a burst.
        burst_conversation = owner.new_session()
        peers = [client() for _ in range(8)]
        barrier = Barrier(8)

        def burst(index: int) -> dict[str, Any]:
            request_id = "load_burst_" + str(index)
            barrier.wait(timeout=30)
            try:
                response = peers[index].send_message(
                    burst_conversation, f"本轮并发提交标记是 B{index}。", request_id=request_id
                )
                return {
                    "request_id": request_id,
                    "status": "accepted",
                    "id": response["user"]["id"],
                }
            except DriverError as exc:
                if str(exc) == "HTTP 409: /api/chat":
                    return {"request_id": request_id, "status": "busy"}
                raise

        with ThreadPoolExecutor(max_workers=8) as pool:
            burst_rows = list(pool.map(burst, range(8)))
        history = owner.read_history(burst_conversation)
        stored = {row["request_id"] for row in history if row["role"] == "user"}
        accepted = {row["request_id"] for row in burst_rows if row["status"] == "accepted"}
        if not accepted or stored != accepted:
            raise AssertionError("HTTP admission did not match the durable ledger")
        record(
            {
                "kind": "burst",
                "accepted": len(accepted),
                "busy": 8 - len(accepted),
                "no_lost_or_phantom_writes": True,
                "rows": burst_rows,
            }
        )

        # An acknowledged retry must not create another source or model answer.
        key = "load_idempotent_" + uuid4().hex
        first = owner.send_message(burst_conversation, "幂等复测标记 K943。", request_id=key)
        second = owner.send_message(burst_conversation, "幂等复测标记 K943。", request_id=key)
        same = first["user"]["id"] == second["user"]["id"] and (
            first["assistant"]["id"] == second["assistant"]["id"]
        )
        if not same:
            raise AssertionError("replayed acknowledged request duplicated a source or answer")
        before = owner.read_history(conversation)
        owner = instance.restart()
        after = owner.read_history(conversation)
        if [row["id"] for row in before] != [row["id"] for row in after]:
            raise AssertionError("acknowledged conversation changed after process restart")
        query_session = owner.new_session()
        source = sources[0]
        answer = owner.send_message(query_session, f"档案 {source['key']} 的封套保存在什么柜？")
        evidence = final_evidence(answer)
        if source["id"] not in evidence or source["value"] not in evidence:
            raise AssertionError("restart lost source recall")
        result.update(
            status="passed",
            idempotency_passed=same,
            restart_passed=True,
            identity=owner.request("GET", "/api/testing/discover"),
        )
    except Exception as exc:
        result.update(status="failed", error=repr(exc))
        if isinstance(exc, DriverError):
            result["failure_evidence"] = exc.evidence
        raise
    finally:
        instance.stop()
        write_json(instance.directory / "load-results.json", result)
        print(
            json.dumps(
                {"event": "finished", "run_id": instance.run_id, "status": result["status"]}
            ),
            flush=True,
        )
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
