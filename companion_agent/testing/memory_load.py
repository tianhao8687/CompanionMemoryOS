"""Bounded offline memory load test with an independent synthetic source oracle.

This exercises ApplicationMemory and real SQLite transactions, not language quality.
Every run owns a fresh directory; no daily-use database or remote model is accepted.
"""

from __future__ import annotations

import argparse
import cProfile
import ctypes
import hashlib
import json
import os
import platform
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any
from uuid import uuid4

from companion_agent.cognition import ApplicationMemory, CognitionSettings, Embeddings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.testing.control import fingerprint
from companion_agent.testing.retrieval_benchmark import evidence_metrics, percentile, write_json
from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    AnswerCardinality,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryInput,
    MemoryKind,
    MemoryRecord,
    MemoryScope,
    MemoryStatus,
    RecallRequest,
    StateQuery,
)
from companion_memoryos.store import MemoryStore

SEED = 20261003
SCOPE = MemoryScope(companion_id="load-companion", relationship_id="synthetic-load")
OWNER = "synthetic-owner"
START = datetime(2026, 1, 1, tzinfo=UTC)


def latency(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "p50": percentile(values, 0.5),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "max": max(values),
    }


def process_resources() -> dict[str, float | int]:
    result: dict[str, float | int] = {"cpu_seconds": time.process_time()}
    if os.name == "nt":

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("faults", ctypes.c_ulong),
                ("peak_rss", ctypes.c_size_t),
                ("rss", ctypes.c_size_t),
                ("peak_paged", ctypes.c_size_t),
                ("paged", ctypes.c_size_t),
                ("peak_nonpaged", ctypes.c_size_t),
                ("nonpaged", ctypes.c_size_t),
                ("pagefile", ctypes.c_size_t),
                ("peak_pagefile", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        info = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        info.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        if info(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            result.update(rss_bytes=counters.rss, peak_rss_bytes=counters.peak_rss)
    return result


def corpus_row(index: int, seed: int) -> dict[str, str]:
    digest = hashlib.sha256(f"{seed}:{index}".encode()).hexdigest()
    key, value = "ZX" + digest[:12], "柜" + digest[16:24]
    fact = f"物品 {key} 的保管位置是{value}，登记人已完成核对。"
    # Periodically place the fact inside a long, repetitive source.
    if index % 25 == 0:
        padding = "日常检查记录：整理空盒，清扫地面，核对登记。" * 24
        fact = padding + fact + padding
    return {"key": key, "value": value, "content": fact}


def make_memory(directory: Path) -> ApplicationMemory:
    config = load_config()
    database = Database(directory, config)
    database.initialize()
    memory = ApplicationMemory(MemoryStore(database), config)
    memory.configure(
        CognitionSettings(extract_memory=False, embedding_backend="off"),
        offline=True,
        model=DeepSeekConfig(),
        key=None,
    )
    return memory


class Workload:
    def __init__(self, directory: Path, seed: int, deadline: float) -> None:
        self.directory = directory
        self.seed = seed
        self.deadline = deadline
        self.memory = make_memory(directory / "database")
        self.database = self.memory.store.database
        self.embeddings = Embeddings(CognitionSettings(embedding_backend="local"), offline=True)
        self.sources: list[dict[str, str]] = []
        self.canaries: set[str] = set()

    def check_time(self) -> None:
        if time.monotonic() > self.deadline:
            raise TimeoutError("load test wall-time budget exhausted")

    def seed_to(self, count: int) -> dict[str, Any]:
        timings = []
        start = time.perf_counter()
        with self.database.session():
            for index in range(len(self.sources), count):
                self.check_time()
                row = corpus_row(index, self.seed)
                before = time.perf_counter()
                source = self.memory.append_turn(
                    ConversationTurnInput(
                        user_id=OWNER,
                        scope=SCOPE.model_copy(
                            update={"conversation_id": f"archive-{index // 100}"}
                        ),
                        actor_id=OWNER,
                        role=ConversationRole.USER,
                        content=row["content"],
                        consent=ConsentState.GRANTED,
                        occurred_at=START + timedelta(seconds=index),
                        embedding=self.embeddings.encode(row["content"]),
                        embedding_space=self.embeddings.space,
                    )
                ).turn
                if source is None:
                    raise AssertionError("source append was rejected")
                timings.append((time.perf_counter() - before) * 1000)
                self.sources.append({**row, "id": source.id})
                # Same literal key and a wrong answer in another relationship.
                if index % 100 == 0:
                    canary = self.memory.append_turn(
                        ConversationTurnInput(
                            user_id=OWNER,
                            scope=SCOPE.model_copy(
                                update={
                                    "relationship_id": "other-relationship",
                                    "conversation_id": "isolation-canary",
                                }
                            ),
                            actor_id=OWNER,
                            role=ConversationRole.USER,
                            content=f"物品 {row['key']} 的保管位置是错误的隔离柜。",
                            consent=ConsentState.GRANTED,
                            occurred_at=START,
                        )
                    ).turn
                    if canary is None:
                        raise AssertionError("canary append was rejected")
                    self.canaries.add(canary.id)
        return {
            "source_count": count,
            "scope_canaries": len(self.canaries),
            "seconds": time.perf_counter() - start,
            "append_with_hash_encoding_ms": latency(timings),
        }

    def query(self, indices: list[int], mode: str) -> dict[str, Any]:
        self.check_time()
        sources = [self.sources[index] for index in indices]
        question = "、".join(source["key"] for source in sources) + " 的保管位置分别在哪里？"
        gold = {source["id"] for source in sources}
        start = time.perf_counter()
        retrieved: list[str] = []
        row: dict[str, Any] = {"indices": indices, "mode": mode, "status": "completed"}
        try:
            vector = self.embeddings.encode(question) if mode == "hash" else None
            request = RecallRequest(
                user_id=OWNER,
                scope=SCOPE.model_copy(update={"conversation_id": "query-session"}),
                query=question,
                include_turn_evidence=True,
                include_relationship_turns=True,
                answer_cardinality=AnswerCardinality.OPEN,
                as_of=START + timedelta(days=2),
                turn_limit=6,
                max_tokens=2500,
                max_characters=12000,
                query_embedding=vector,
                embedding_space=self.embeddings.space if vector is not None else None,
            )
            with self.database.session():
                context = self.memory.recall(request)
            retrieved = [item.turn.id for item in context.turn_fallback]
            row["wrong_scope"] = bool(set(retrieved) & self.canaries) or any(
                item.turn.scope.relationship_id != SCOPE.relationship_id
                for item in context.turn_fallback
            )
            text_by_id = {item.turn.id: item.evidence_text for item in context.turn_fallback}
            row["answer_spans_complete"] = all(
                source["value"] in text_by_id.get(source["id"], "") for source in sources
            )
            row["rendered_tokens"] = context.rendered_tokens
            row["budget_exhausted"] = context.budget_exhausted
        except Exception as exc:
            row.update(status="failed", error=repr(exc), answer_spans_complete=False)
        row["latency_ms"] = (time.perf_counter() - start) * 1000
        row["retrieved"] = retrieved
        row["gold"] = sorted(gold)
        row["metrics"] = {str(k): evidence_metrics(retrieved, gold, k) for k in (1, 3, 6)}
        return row

    def read_phase(self, count: int, workers: int, mode: str) -> dict[str, Any]:
        rng = random.Random(self.seed + len(self.sources))
        queries = [
            rng.sample(range(len(self.sources)), 4 if index % 4 == 0 else 1)
            for index in range(count)
        ]
        # Long sources and old sources are explicit strata, not left to chance.
        queries[:2] = [[0], [min(25, len(self.sources) - 1)]]
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = list(pool.map(lambda indices: self.query(indices, mode), queries))
        elapsed = time.perf_counter() - started
        self.save_rows(rows)
        groups = {
            label: [row for row in rows if (len(row["gold"]) > 1) == multi]
            for label, multi in (("single", False), ("multi", True))
        }
        return {
            "source_count": len(self.sources),
            "workers": workers,
            "mode": mode,
            "requests": len(rows),
            "errors": sum(row["status"] != "completed" for row in rows),
            "wrong_scope": sum(row.get("wrong_scope", False) for row in rows),
            "seconds": elapsed,
            "requests_per_second": len(rows) / elapsed,
            "latency_ms": latency([row["latency_ms"] for row in rows]),
            "quality": {
                label: {
                    "n": len(group),
                    "hit_at_1": statistics.mean(row["metrics"]["1"]["hit"] for row in group),
                    "recall_at_6": statistics.mean(row["metrics"]["6"]["recall"] for row in group),
                    "all_evidence_at_6": statistics.mean(
                        row["metrics"]["6"]["all_evidence"] for row in group
                    ),
                    "answer_spans_complete": sum(row["answer_spans_complete"] for row in group),
                }
                for label, group in groups.items()
                if group
            },
        }

    def save_rows(self, rows: list[dict[str, Any]]) -> None:
        with (self.directory / "operations.jsonl").open("a", encoding="utf-8") as handle:
            for row in rows:
                row["source_count"] = len(self.sources)
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def mixed_phase(self, workers: int, operations: int) -> dict[str, Any]:
        gate = Barrier(workers)

        def worker(number: int) -> list[dict[str, Any]]:
            rows = []
            gate.wait(timeout=30)
            for step in range(operations):
                self.check_time()
                if (number + step) % 2:
                    row = self.query([(number * operations + step) % len(self.sources)], "fts")
                    row["operation"] = "read"
                else:
                    start = time.perf_counter()
                    row = {"operation": "write", "status": "completed"}
                    slot = (number + step // 2) % 4
                    try:
                        with self.database.session():
                            record = self.memory.remember(
                                MemoryInput(
                                    user_id=OWNER,
                                    scope=SCOPE,
                                    kind=MemoryKind.PREFERENCE,
                                    title=f"并发槽位 {slot}",
                                    content=(
                                        f"槽位 {slot} 的当前登记值是 w{workers}-{number}-{step}。"
                                    ),
                                    stable_key=f"mixed-{workers}-{slot}",
                                    predicate=f"mixed-{workers}-{slot}",
                                    consent=ConsentState.GRANTED,
                                    explicit_user_request=True,
                                )
                            ).memory
                            if record is None:
                                raise AssertionError("write returned no durable record")
                            state = self.memory.query_state(
                                StateQuery(
                                    user_id=OWNER, scope=SCOPE, predicate=f"mixed-{workers}-{slot}"
                                )
                            )
                            if len(state.memories) != 1:
                                raise AssertionError("state did not resolve to one current version")
                        row.update(id=record.id, slot=slot)
                    except Exception as exc:
                        row.update(status="failed", error=repr(exc))
                    row["latency_ms"] = (time.perf_counter() - start) * 1000
                rows.append(row)
            return rows

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows = [row for group in pool.map(worker, range(workers)) for row in group]
        elapsed = time.perf_counter() - started
        self.save_rows(rows)
        writes = [row for row in rows if row["operation"] == "write"]
        expected = {row["id"] for row in writes if row["status"] == "completed"}
        records = self.memory.store.list_memories(OWNER)
        records = [record for record in records if record.id in expected]
        visited: set[str] = set()
        by_id = {record.id: record for record in records}
        active_keys = [
            record.stable_key for record in records if record.status is MemoryStatus.ACTIVE
        ]
        chain_order_valid = True
        for record in records:
            if record.status is not MemoryStatus.ACTIVE:
                continue
            current: MemoryRecord | None = record
            while current:
                if current.id in visited:
                    raise AssertionError("version chain cycle or shared parent")
                visited.add(current.id)
                parent = by_id.get(current.supersedes_id or "")
                if parent is not None:
                    chain_order_valid = chain_order_valid and (
                        parent.status is MemoryStatus.SUPERSEDED
                        and parent.valid_to == current.valid_from
                        and parent.valid_from <= current.valid_from
                    )
                current = parent
        with self.database.connection() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        return {
            "workers": workers,
            "requests": len(rows),
            "errors": sum(row["status"] != "completed" for row in rows),
            "seconds": elapsed,
            "requests_per_second": len(rows) / elapsed,
            "read_ms": latency([row["latency_ms"] for row in rows if row["operation"] == "read"]),
            "write_and_readback_ms": latency([row["latency_ms"] for row in writes]),
            "acknowledged_writes": len(expected),
            "durable_versions": len(records),
            "version_chains_complete": visited == expected,
            "version_order_valid": chain_order_valid,
            "one_current_per_slot": len(active_keys) == len(set(active_keys)),
            "integrity_ok": integrity == "ok" and not foreign_keys,
            "read_failures": sum(
                not row["answer_spans_complete"] or row.get("wrong_scope", False)
                for row in rows
                if row["operation"] == "read"
            ),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 10000])
    parser.add_argument("--workers", nargs="+", type=int, default=[1, 4, 8, 16])
    parser.add_argument("--queries", type=int, default=64)
    parser.add_argument("--mixed-per-worker", type=int, default=20)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    if not all(4 <= size <= 100000 for size in args.sizes):
        parser.error("sizes must be between 4 and 100000")
    if not all(1 <= size <= 32 for size in args.workers):
        parser.error("workers must be between 1 and 32")
    if not 4 <= args.queries <= 1000 or not 2 <= args.mixed_per_worker <= 200:
        parser.error("queries must be 4..1000; mixed-per-worker must be 2..200")
    if not 1 <= args.timeout <= 3600:
        parser.error("timeout must be 1..3600 seconds")
    directory = Path(".agent-tests/memory-load") / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    protocol = {
        "run_id": directory.name,
        "code_sha256": fingerprint(),
        "arguments": vars(args),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "remote_model_calls": 0,
        "measurement": (
            "service calls; includes SQLite and hash encoding; excludes HTTP and generation"
        ),
        "load_model": "closed loop; bounded worker count, no automatic retries",
        "quality_target": (
            "all exact synthetic source IDs and answer spans retained; zero scope leaks"
        ),
        "integrity_target": "zero errors or lost acknowledged writes; complete version chains",
    }
    write_json(directory / "protocol.json", protocol)
    result: dict[str, Any] = {"run_id": directory.name, "status": "running", "phases": []}
    workload = Workload(directory, args.seed, time.monotonic() + args.timeout)

    def record(kind: str, phase: dict[str, Any]) -> None:
        phase["kind"] = kind
        phase["resources"] = process_resources()
        result["phases"].append(phase)
        write_json(directory / "results.json", result)
        print(json.dumps({"event": kind, **phase}), flush=True)

    print(json.dumps({"event": "started", **protocol}), flush=True)
    try:
        for size in sorted(set(args.sizes)):
            record("seed", workload.seed_to(size))
            for mode in ("fts", "hash"):
                record("serial", workload.read_phase(args.queries, 1, mode))
        profile = cProfile.Profile()
        profile.runcall(workload.query, [0], "hash")
        profile.dump_stats(str(directory / "recall-profile.pstats"))
        for workers in args.workers:
            record("concurrent", workload.read_phase(args.queries, workers, "hash"))
            record("mixed", workload.mixed_phase(workers, args.mixed_per_worker))
        result["validation"] = {
            "accuracy": all(
                group["answer_spans_complete"] == group["n"]
                for phase in result["phases"]
                for group in phase.get("quality", {}).values()
            ),
            "integrity": all(
                not phase.get("errors", 0)
                and not phase.get("wrong_scope", 0)
                and not phase.get("read_failures", 0)
                and all(
                    phase.get(key, True)
                    for key in (
                        "version_chains_complete",
                        "version_order_valid",
                        "one_current_per_slot",
                        "integrity_ok",
                    )
                )
                for phase in result["phases"]
            ),
        }
        result["status"] = "passed" if all(result["validation"].values()) else "failed"
        result["database_bytes"] = workload.database.path.stat().st_size
    except Exception as exc:
        result.update(status="failed", error=repr(exc))
        raise
    finally:
        workload.memory.close_indexer()
        write_json(directory / "results.json", result)
        print(
            json.dumps({"event": "finished", "run_id": directory.name, "status": result["status"]}),
            flush=True,
        )
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
