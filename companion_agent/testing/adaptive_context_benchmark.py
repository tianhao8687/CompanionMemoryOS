"""Paired fixed/adaptive final-context retrieval on an owned, frozen public corpus.

No generated answers or remote calls. Every query is rolled back to the same corpus
after actual CompanionAgent.prepare; this latency excludes HTTP and durable commits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from companion_agent import CompanionAgent, load_persona
from companion_agent.cognition import ApplicationMemory, CognitionSettings, Embeddings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.testing.control import fingerprint
from companion_agent.testing.retrieval_benchmark import (
    TOP_K,
    Encoder,
    distribution,
    encoder_for,
    evidence_metrics,
    write_json,
)
from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from companion_memoryos.diagnostics import sink
from companion_memoryos.schemas import ConsentState, MemoryScope, ProcessTurnRequest
from companion_memoryos.store import MemoryStore


class LocalCorpusEmbeddings(Embeddings):
    def __init__(self, encoder: Encoder, space: str) -> None:
        super().__init__(CognitionSettings(embedding_backend="local"), offline=True)
        self.encoder = encoder
        self.space = space
        self.calls = 0

    def encode(self, text: str) -> list[float]:
        self.calls += 1
        return self.encoder([text])[0]


class Observer:
    def __init__(self) -> None:
        self.events: dict[str, Any] = {}

    def begin_call(self, source: str, payload: dict[str, Any], live: bool) -> dict[str, Any]:
        raise RuntimeError("This benchmark does not authorize model adapter calls")

    def finish_call(self, call: dict[str, Any]) -> None:
        pass

    def event(self, name: str, value: Any) -> None:
        self.events[name] = value


def evidence_from_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for message in messages:
        content = message.get("content", "")
        marker = "[RELEVANT MEMORY]\n"
        if (
            message.get("role") == "user"
            and isinstance(content, str)
            and content.startswith("[APPLICATION CONTEXT]")
            and marker in content
        ):
            return cast(
                list[dict[str, Any]],
                json.JSONDecoder().raw_decode(content.split(marker, 1)[1])[0]["evidence"],
            )
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", required=True)
    parser.add_argument("--mode", choices=("fts", "hash", "bge"), default="bge")
    parser.add_argument("--max-questions", type=int)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--bge-cache", type=Path, default=Path(".agent-data/embeddings"))
    parser.add_argument("--runtime-dir", type=Path, default=Path(".agent-data/embeddings/runtime"))
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9-]{36}", args.source_run):
        parser.error("source-run must be an owned public retrieval benchmark run ID")
    source = Path(".agent-tests/retrieval-benchmarks") / args.source_run
    root = Path(".agent-tests/adaptive-context") / str(uuid4())
    root.mkdir(parents=True, exist_ok=False)
    corpus_rows = [
        json.loads(line)
        for line in (source / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    rows = [row for row in corpus_rows if row["mode"] == args.mode]
    if args.max_questions is not None:
        rows = rows[: args.max_questions]
    if not rows:
        parser.error("source run has no questions for the requested mode")
    protocol = {
        "run_id": root.name,
        "source_run": args.source_run,
        "mode": args.mode,
        "source_protocol_sha256": hashlib.sha256(
            (source / "protocol.json").read_bytes()
        ).hexdigest(),
        "question_ids": [row["id"] for row in rows],
        "code": fingerprint(),
        "input_context_limit": 16000,
        "turn_source_limit": 6,
        "profiles": {
            "fixed": "2500 tokens / 12000 characters",
            "adaptive": "task ceiling 4K/8K, final whole-context fit",
        },
        "layer": "CompanionAgent.prepare final messages; no generated answer or HTTP",
        "reset": "savepoint rollback after every profile; source databases copied read-only",
        "index": "preindexed corpus, background indexing stopped; local query encoding included",
        "remote_calls": 0,
        "timeout_seconds": args.timeout,
    }
    write_json(root / "protocol.json", protocol)
    result: dict[str, Any] = {"run_id": root.name, "status": "running", "profiles": {}}
    write_json(root / "results.json", result)
    print(json.dumps({"event": "started", "run_id": root.name, "questions": len(rows)}), flush=True)
    deadline = time.monotonic() + args.timeout
    records: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["sample"]].append(row)
    try:
        encoder, space = encoder_for(args.mode, args)
        for sample, questions in grouped.items():
            if not re.fullmatch(r"[a-f0-9]{12}", sample):
                raise ValueError("invalid corpus sample ID")
            directory = root / sample
            directory.mkdir()
            source_db = (source / args.mode / sample / "companion-memoryos.db").resolve()
            with (
                sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as reader,
                sqlite3.connect(directory / "companion-memoryos.db") as writer,
            ):
                reader.backup(writer)
            config = load_config()
            database = Database(directory, config)
            memory = ApplicationMemory(MemoryStore(database), config)
            memory.configure(
                CognitionSettings(extract_memory=False, embedding_backend="off"),
                offline=True,
                model=DeepSeekConfig(),
                key=None,
            )
            # The frozen corpus already has vectors. Do not index test questions as evidence.
            memory.close_indexer()
            local = LocalCorpusEmbeddings(encoder, space) if encoder and space else None
            if local:
                memory.embeddings = local
            agents = {
                profile: CompanionAgent(memory, load_persona(), adaptive_memory_budget=adaptive)
                for profile, adaptive in (("fixed", False), ("adaptive", True))
            }
            with database.connection() as db:
                canonical = db.execute("SELECT id, source_ref FROM conversation_turns").fetchall()
            identifiers = {turn["id"]: turn["source_ref"].split(":", 2)[2] for turn in canonical}
            try:
                for index, question in enumerate(questions):
                    if time.monotonic() > deadline:
                        raise TimeoutError("adaptive benchmark time budget exhausted")
                    # Alternate order so one profile does not always receive a warmer cache.
                    profiles = ("fixed", "adaptive") if index % 2 == 0 else ("adaptive", "fixed")
                    for profile in profiles:
                        observer = Observer()
                        token = sink.set(observer)
                        calls_before = local.calls if local else 0
                        row = {
                            "id": question["id"],
                            "sample": sample,
                            "profile": profile,
                            "question": question["question"],
                            "gold": question["gold"],
                        }
                        retrieved: list[str] = []
                        started = time.perf_counter()
                        try:
                            with database.connection() as db:
                                db.execute("SAVEPOINT adaptive_query")
                                try:
                                    prepared = agents[profile].prepare(
                                        ProcessTurnRequest(
                                            user_id="locomo:" + sample,
                                            scope=MemoryScope(
                                                companion_id="benchmark",
                                                relationship_id=sample,
                                                conversation_id="adaptive-query",
                                            ),
                                            content=question["question"],
                                            idempotency_key=question["id"],
                                            consent=ConsentState.GRANTED,
                                            model_consent=ConsentState.GRANTED,
                                        )
                                    )
                                    elapsed = (time.perf_counter() - started) * 1000
                                    messages = [
                                        m.model_dump(mode="json") for m in prepared.context.messages
                                    ]
                                    evidence = evidence_from_messages(messages)
                                    retrieved = [
                                        identifiers[item["id"]]
                                        for item in evidence
                                        if item.get("kind") == "turn" and item["id"] in identifiers
                                    ]
                                    allocation = observer.events["memory_allocation"]
                                    if allocation["context_tokens"] > 16000:
                                        raise AssertionError("whole-context budget exceeded")
                                    row.update(
                                        status="completed",
                                        total_ms=elapsed,
                                        allocation=allocation,
                                        evidence=evidence,
                                        messages=messages,
                                    )
                                finally:
                                    db.execute("ROLLBACK TO adaptive_query")
                                    db.execute("RELEASE adaptive_query")
                                if db.execute("SELECT count(*) FROM conversation_turns").fetchone()[
                                    0
                                ] != len(canonical):
                                    raise AssertionError("query contaminated the next trial")
                        except Exception as error:
                            retrieved = []
                            row.update(
                                status="failed", error_type=type(error).__name__, error=str(error)
                            )
                        finally:
                            sink.reset(token)
                        row["embedding_calls"] = local.calls - calls_before if local else 0
                        row["retrieved"] = retrieved
                        row["metrics"] = {
                            str(k): evidence_metrics(retrieved, set(question["gold"]), k)
                            for k in TOP_K
                        }
                        records.append(row)
                        with (root / "queries.jsonl").open("a", encoding="utf-8") as output:
                            output.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(
                    json.dumps({"sample": sample, "profiles_completed": len(records)}), flush=True
                )
            finally:
                memory.close_indexer()
        for profile in ("fixed", "adaptive"):
            selected = [row for row in records if row["profile"] == profile]
            completed = [row for row in selected if row["status"] == "completed"]
            result["profiles"][profile] = {
                "queries": len(selected),
                "failed": len(selected) - len(completed),
                "metrics": {
                    str(k): {
                        name: sum(row["metrics"][str(k)][name] for row in selected) / len(selected)
                        for name in ("hit", "recall", "all_evidence", "precision")
                    }
                    for k in TOP_K
                },
                "prepare_ms": distribution([row["total_ms"] for row in completed]),
                "context_tokens": distribution(
                    [row["allocation"]["context_tokens"] for row in completed]
                ),
                "allocation_reductions": sum(
                    row["allocation"]["allocation_attempts"] > 0 for row in completed
                ),
                "embedding_calls": sum(row["embedding_calls"] for row in selected),
            }
        result["status"] = (
            "completed" if all(row["status"] == "completed" for row in records) else "failed"
        )
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__, error=str(error))
    finally:
        result["profiles_recorded"] = len(records)
        write_json(root / "results.json", result)
        print(json.dumps(result), flush=True)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
