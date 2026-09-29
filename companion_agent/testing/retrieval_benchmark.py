"""Reproducible, offline LoCoMo evidence retrieval through ApplicationMemory.

This measures the raw-turn retrieval path, not extraction or generated QA accuracy.
Only local hash vectors or an explicitly selected, cached local BGE model are used.
Downloaded data, labels, databases and per-question results stay in .agent-tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import statistics
import subprocess
import time
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from companion_agent.cognition import ApplicationMemory, CognitionSettings, Embeddings
from companion_agent.deepseek import DeepSeekConfig
from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    AnswerCardinality,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryScope,
    RecallRequest,
)
from companion_memoryos.store import MemoryStore

SOURCE_COMMIT = "3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376"
SOURCE_URL = (
    f"https://raw.githubusercontent.com/snap-research/locomo/{SOURCE_COMMIT}/data/locomo10.json"
)
SOURCE_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
TOP_K = (1, 3, 6)
Encoder = Callable[[list[str]], list[list[float]]]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def evidence_metrics(retrieved: list[str], gold: set[str], k: int) -> dict[str, float]:
    """Missing result slots count against P@k; empty gold is never scored as success."""
    if not gold or k < 1:
        raise ValueError("metrics require nonempty gold and positive k")
    if len(set(retrieved)) != len(retrieved):
        raise ValueError("retrieved IDs must be unique")
    selected = retrieved[:k]
    hits = len(set(selected) & gold)
    return {
        "recall": hits / len(gold),
        "precision": hits / k,
        "returned_precision": hits / len(selected) if selected else 0.0,
        "hit": float(hits > 0),
        "all_evidence": float(hits == len(gold)),
        "reciprocal_rank": next(
            (1.0 / rank for rank, identifier in enumerate(selected, 1) if identifier in gold), 0.0
        ),
    }


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def distribution(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "p50": statistics.median(values),
        "p95": percentile(values, 0.95),
        "min": min(values),
        "max": max(values),
    }


def load_conversation(sample: dict[str, Any]) -> tuple[list[dict[str, Any]], datetime]:
    conversation = sample["conversation"]
    sessions = sorted(
        (key for key in conversation if re.fullmatch(r"session_\d+", key)),
        key=lambda key: int(key.split("_")[1]),
    )
    turns: list[dict[str, Any]] = []
    for session in sessions:
        timestamp = datetime.strptime(
            conversation[session + "_date_time"], "%I:%M %p on %d %B, %Y"
        ).replace(tzinfo=UTC)
        for index, turn in enumerate(conversation[session]):
            content = f"{turn['speaker']}: {turn['text']}"
            if turn.get("blip_caption"):
                content += "\nImage caption: " + turn["blip_caption"]
            turns.append(
                {
                    "id": turn["dia_id"],
                    "speaker": turn["speaker"],
                    "session": session,
                    "content": content,
                    "occurred_at": timestamp + timedelta(seconds=index),
                }
            )
    if not turns or len({turn["id"] for turn in turns}) != len(turns):
        raise ValueError("conversation must contain uniquely identified turns")
    return turns, max(turn["occurred_at"] for turn in turns) + timedelta(days=1)


def select_questions(
    sample: dict[str, Any], identifiers: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected, excluded = [], []
    for index, item in enumerate(sample["qa"]):
        evidence = item.get("evidence", [])
        row = {"id": f"{sample['sample_id']}:{index}", "category": item["category"]}
        if item["category"] == 5:
            reason = "adversarial_no_positive_retrieval_target"
        elif not evidence:
            reason = "no_annotated_evidence"
        elif not isinstance(evidence, list) or any(
            not isinstance(identifier, str) or identifier not in identifiers
            for identifier in evidence
        ):
            reason = "unresolvable_evidence_id"
        else:
            selected.append({**row, "question": item["question"], "gold": sorted(set(evidence))})
            continue
        excluded.append({**row, "reason": reason, "evidence": evidence})
    return selected, excluded


def encoder_for(mode: str, args: argparse.Namespace) -> tuple[Encoder | None, str | None]:
    if mode == "fts":
        return None, None
    if mode == "hash":
        embeddings = Embeddings(CognitionSettings(embedding_backend="local"), offline=True)
        return lambda texts: [embeddings.encode(text) for text in texts], embeddings.space
    from companion_agent.embedding_server import MODEL, load_encoder

    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    return load_encoder(args.bge_cache, 4, args.runtime_dir), "benchmark-local:" + MODEL


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row["status"] == "completed"]
    output: dict[str, Any] = {
        "questions": len(rows),
        "completed": len(completed),
        "failed": len(rows) - len(completed),
    }
    # Failed queries retain zero scores and remain in every quality denominator.
    output["metrics"] = (
        {
            str(k): {
                name: statistics.mean(row["metrics"][str(k)][name] for row in rows)
                for name in (
                    "recall",
                    "precision",
                    "returned_precision",
                    "hit",
                    "all_evidence",
                    "reciprocal_rank",
                )
            }
            for k in TOP_K
        }
        if rows
        else {}
    )
    output["latency_ms"] = {
        name: distribution([row[name] for row in completed])
        for name in ("embedding_ms", "retrieval_ms", "total_ms")
    }
    output["budget_exhausted"] = sum(row.get("budget_exhausted", False) for row in completed)
    return output


def evaluate_sample(
    directory: Path,
    sample: dict[str, Any],
    mode: str,
    encoder: Encoder | None,
    space: str | None,
    max_questions: int | None,
    deadline: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    turns, as_of = load_conversation(sample)
    questions, excluded = select_questions(sample, {turn["id"] for turn in turns})
    if max_questions is not None:
        questions = questions[:max_questions]
    config = load_config()
    database = Database(directory / mode / sample["sample_id"], config)
    database.initialize()
    memory = ApplicationMemory(MemoryStore(database), config)
    memory.configure(
        CognitionSettings(extract_memory=False, embedding_backend="off"),
        offline=True,
        model=DeepSeekConfig(),
        key=None,
    )
    scope = MemoryScope(companion_id="benchmark", relationship_id=sample["sample_id"])
    user_id = "locomo:" + sample["sample_id"]
    id_map = {}
    embedding_seconds = 0.0
    storage_seconds = 0.0
    for offset in range(0, len(turns), 16):
        if time.monotonic() > deadline:
            raise TimeoutError("benchmark time budget exhausted")
        batch = turns[offset : offset + 16]
        started = time.perf_counter()
        vectors = encoder([turn["content"] for turn in batch]) if encoder else None
        embedding_seconds += time.perf_counter() - started
        started = time.perf_counter()
        with database.session():
            for index, turn in enumerate(batch):
                stored = memory.append_turn(
                    ConversationTurnInput(
                        user_id=user_id,
                        scope=scope.model_copy(update={"conversation_id": turn["session"]}),
                        actor_id=turn["speaker"],
                        role=ConversationRole.USER,
                        content=turn["content"],
                        consent=ConsentState.GRANTED,
                        occurred_at=turn["occurred_at"],
                        source_ref=f"locomo:{sample['sample_id']}:{turn['id']}",
                        embedding=vectors[index] if vectors is not None else None,
                        embedding_space=space,
                    )
                )
                if stored.turn is None or not stored.stored:
                    raise ValueError("benchmark turn was not stored")
                id_map[stored.turn.id] = turn["id"]
        storage_seconds += time.perf_counter() - started
    rows = []
    with (directory / "queries.jsonl").open("a", encoding="utf-8") as evidence:
        for question in questions:
            if time.monotonic() > deadline:
                raise TimeoutError("benchmark time budget exhausted")
            row: dict[str, Any] = {**question, "mode": mode, "sample": sample["sample_id"]}
            start = time.perf_counter()
            retrieved: list[str] = []
            try:
                vector = encoder([question["question"]])[0] if encoder else None
                encoded = time.perf_counter()
                request = RecallRequest(
                    user_id=user_id,
                    scope=scope.model_copy(update={"conversation_id": "benchmark-query"}),
                    query=question["question"],
                    as_of=as_of,
                    include_turn_evidence=True,
                    include_relationship_turns=True,
                    answer_cardinality=AnswerCardinality.OPEN,
                    limit=4,
                    turn_limit=6,
                    max_tokens=2500,
                    max_characters=12000,
                    query_embedding=vector,
                    embedding_space=space,
                )
                with database.session():
                    context = memory.recall(request)
                finished = time.perf_counter()
                retrieved = [id_map[item.turn.id] for item in context.turn_fallback]
                row.update(
                    status="completed",
                    embedding_ms=(encoded - start) * 1000,
                    retrieval_ms=(finished - encoded) * 1000,
                    total_ms=(finished - start) * 1000,
                    budget_exhausted=context.budget_exhausted,
                    rendered_tokens=context.rendered_tokens,
                    semantic_matches=sum(item.semantic > 0 for item in context.turn_fallback),
                    scores=[
                        {
                            "id": id_map[item.turn.id],
                            "lexical": item.lexical,
                            "semantic": item.semantic,
                            "use_mode": item.use_mode.value,
                        }
                        for item in context.turn_fallback
                    ],
                )
            except Exception as exc:
                row.update(status="failed", error_type=type(exc).__name__, error=str(exc))
            row["retrieved"] = retrieved
            row["metrics"] = {
                str(k): evidence_metrics(retrieved, set(question["gold"]), k) for k in TOP_K
            }
            evidence.write(json.dumps(row, ensure_ascii=False) + "\n")
            evidence.flush()
            rows.append(row)
    return rows, {
        "sample": sample["sample_id"],
        "mode": mode,
        "turns": len(turns),
        "questions": len(questions),
        "excluded": excluded,
        "ingestion_embedding_seconds": embedding_seconds,
        "storage_seconds": storage_seconds,
        "database_bytes": database.path.stat().st_size,
    }


def render_report(result: dict[str, Any]) -> str:
    lines = [
        "# Memory retrieval benchmark",
        "",
        f"Run ID: `{result['run_id']}`",
        "",
        f"Status: {result['status']}",
        "",
        "Raw public dialogue evidence only. No remote model calls, model extraction, "
        "generated answers or official LoCoMo QA score.",
        "",
        "| Mode | Questions | Evidence recall@6 | Any hit@6 | All evidence@6 | Precision@6 | "
        "Total p50 ms | Total p95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode, summary in result["summaries"].items():
        if not summary["questions"]:
            continue
        metrics = summary["metrics"]["6"]
        latency = summary["latency_ms"]["total_ms"]
        lines.append(
            f"| {mode} | {summary['questions']} | {metrics['recall']:.2%} | "
            f"{metrics['hit']:.2%} | {metrics['all_evidence']:.2%} | "
            f"{metrics['precision']:.2%} | {latency.get('p50', 0):.2f} | "
            f"{latency.get('p95', 0):.2f} |"
        )
    lines += [
        "",
        "## Protocol",
        "",
        "- The frozen protocol and source/config/code fingerprints are in protocol.json.",
        "- Every conversation gets a fresh database per mode; sessions remain separate.",
        "- Both human speakers use user-role turns with distinct actor IDs and speaker prefixes.",
        "- Text and provided image captions are indexed. No QA, gold IDs, generated summaries "
        "or observations enter searchable content; QA is not appended to the ledger.",
        "- ApplicationMemory.recall uses normal candidate completion, privacy/source checks "
        "and the chat path's 6-turn, 2500-token, 12000-character limits.",
        "- Recall is the per-question fraction of annotated evidence found. Any-hit and "
        "all-evidence rates are reported separately. P@k divides by k, including empty slots.",
        "- Adversarial/no-evidence/invalid-ID questions cannot define positive-evidence recall "
        "and are listed as exclusions, not counted as successes.",
        "- Gold evidence may be incomplete; unlabelled helpful context still lowers precision.",
        "- Timings are sequential single-client measurements including query encoding, "
        "SQLite retrieval and prompt rendering, excluding HTTP, extraction and chat generation.",
        "- BGE is the existing Chinese model, cached and CPU-only, called directly without "
        "the HTTP wrapper; 512-token truncation applies. These are English benchmark questions.",
        "- Corpus dates are interpreted as UTC (the dataset provides no timezone); queries "
        "use one day after the final session, not the wall clock date.",
        "- No thresholds or retrieval parameters are tuned after observing answers.",
        "- Full per-question results, including failures, are in queries.jsonl.",
        "- This is not a cold-disk, concurrent-load or end-to-end application benchmark.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--modes", nargs="+", choices=("fts", "hash", "bge"), default=["fts", "hash"]
    )
    parser.add_argument("--max-conversations", type=int)
    parser.add_argument("--max-questions", type=int)
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--bge-cache", type=Path, default=Path(".agent-data/embeddings"))
    parser.add_argument("--runtime-dir", type=Path)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        parser.error("dataset hash differs from the pinned official LoCoMo source")
    for field in (args.max_conversations, args.max_questions, args.timeout):
        if field is not None and field < 1:
            parser.error("limits must be positive")
    samples = json.loads(raw)[: args.max_conversations]
    directory = Path(".agent-tests/retrieval-benchmarks") / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    modes = list(dict.fromkeys(args.modes))
    config = load_config()
    source_hash = hashlib.sha256()
    for path in sorted(
        [*Path("companion_agent").rglob("*.py"), *Path("companion_memoryos").rglob("*.py")]
    ):
        source_hash.update(path.as_posix().encode() + b"\0" + path.read_bytes())
    plan = {
        "run_id": directory.name,
        "source_url": SOURCE_URL,
        "source_commit": SOURCE_COMMIT,
        "dataset_sha256": SOURCE_SHA256,
        "code_sha256": source_hash.hexdigest(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "modes": modes,
        "top_k": TOP_K,
        "max_questions_per_conversation": args.max_questions,
        "sample_ids": [sample["sample_id"] for sample in samples],
        "timeout_seconds": args.timeout,
        "max_embedding_texts": 20000,
        "remote_model_calls": 0,
        "automatic_retries": 0,
        "config": config.model_dump(mode="json"),
        "protocol": "public-raw-turn-evidence-v1",
        "created_at": datetime.now(UTC).isoformat(),
    }
    text_count = sum(len(load_conversation(sample)[0]) + len(sample["qa"]) for sample in samples)
    if text_count > plan["max_embedding_texts"]:
        raise ValueError("local inference input budget exceeded")
    write_json(directory / "protocol.json", plan)
    result: dict[str, Any] = {
        "run_id": directory.name,
        "status": "running",
        "summaries": {},
        "samples": [],
        "errors": [],
        "remote_model_calls": 0,
    }
    deadline = time.monotonic() + args.timeout
    print(
        json.dumps(
            {
                "event": "started",
                "run_id": directory.name,
                "directory": str(directory.resolve()),
                "modes": modes,
            }
        ),
        flush=True,
    )
    try:
        for mode in modes:
            rows: list[dict[str, Any]] = []
            try:
                encoder, space = encoder_for(mode, args)
                for sample in samples:
                    sample_rows, info = evaluate_sample(
                        directory, sample, mode, encoder, space, args.max_questions, deadline
                    )
                    rows.extend(sample_rows)
                    result["samples"].append(info)
                    result["summaries"][mode] = summarize(rows)
                    write_json(directory / "results.json", result)
                    print(
                        json.dumps(
                            {
                                "event": "sample",
                                "mode": mode,
                                **info,
                                "excluded": len(info["excluded"]),
                            }
                        ),
                        flush=True,
                    )
                categories: dict[int, list[dict[str, Any]]] = defaultdict(list)
                for row in rows:
                    categories[row["category"]].append(row)
                result["summaries"][mode]["categories"] = {
                    str(category): summarize(group) for category, group in categories.items()
                }
                result["summaries"][mode]["returned_counts"] = dict(
                    Counter(len(row["retrieved"]) for row in rows)
                )
            except Exception as exc:
                result["errors"].append(
                    {"mode": mode, "type": type(exc).__name__, "error": str(exc)}
                )
                print(json.dumps({"event": "error", **result["errors"][-1]}), flush=True)
        result["status"] = (
            "completed"
            if not result["errors"]
            and not any(summary["failed"] for summary in result["summaries"].values())
            else "failed"
        )
    finally:
        result["finished_at"] = datetime.now(UTC).isoformat()
        write_json(directory / "results.json", result)
        (directory / "report.md").write_text(render_report(result), encoding="utf-8")
    print(
        json.dumps({"event": "finished", "run_id": directory.name, "status": result["status"]}),
        flush=True,
    )
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
