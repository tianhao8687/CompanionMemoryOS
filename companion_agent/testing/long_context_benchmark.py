"""Frozen CLongEval reference-span retrieval, not generated long-context QA accuracy."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from companion_agent.cognition import ApplicationMemory, CognitionSettings
from companion_agent.deepseek import DeepSeekConfig
from companion_agent.testing.retrieval_benchmark import distribution, encoder_for, write_json
from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    AnswerCardinality,
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryScope,
    RealityLayer,
    RecallRequest,
    SpeechSpan,
)
from companion_memoryos.store import MemoryStore

REVISION = "178d74d88f525f494441f94ef8cff9185a3d3b3a"
SOURCE = "https://huggingface.co/datasets/zexuanqiu22/CLongEval"
SEED = "companion-long-zh-v1"
WIDTH, OVERLAP = 320, 64
SIZES = {"small": 12991121, "medium": 55843244, "large": 86831701}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_hash() -> str:
    digest = hashlib.sha256()
    for path in sorted(
        [*Path("companion_agent").rglob("*.py"), *Path("companion_memoryos").rglob("*.py")]
    ):
        digest.update(path.as_posix().encode() + b"\0" + path.read_bytes())
    return digest.hexdigest()


def chunks(text: str, width: int = WIDTH, overlap: int = OVERLAP) -> list[tuple[int, int]]:
    """Query/label-independent windows; offsets refer to the stored, stripped text."""
    if width < 1 or not 0 <= overlap < width:
        raise ValueError("invalid window bounds")
    result = []
    for start in range(0, len(text), width - overlap):
        segment = text[start : start + width]
        left = start + len(segment) - len(segment.lstrip())
        right = start + len(segment.rstrip())
        if right > left:
            result.append((left, right))
        if start + width >= len(text):
            break
    return result


def span_metrics(
    text: str, reference: tuple[int, int], selected: list[tuple[int, int]]
) -> dict[str, float]:
    left, right = reference
    if not 0 <= left < right <= len(text):
        raise ValueError("invalid reference")
    expected = {index for index in range(left, right) if not text[index].isspace()}
    if not expected:
        raise ValueError("empty reference")
    covered: set[int] = set()
    for start, end in selected:
        if not 0 <= start < end <= len(text):
            raise ValueError("invalid retrieved span")
        covered.update(expected.intersection(range(start, end)))
    coverage = len(covered) / len(expected)
    return {
        "coverage": coverage,
        "any_reference": float(bool(covered)),
        "half_reference": float(coverage >= 0.5),
        "full_reference": float(coverage == 1.0),
    }


def prepare(source_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected, exclusions = [], []
    used_questions: set[str] = set()
    source_hashes = {}
    for size, expected_size in SIZES.items():
        path = source_dir / f"clongeval_story_{size}.jsonl"
        if path.stat().st_size != expected_size:
            raise ValueError(f"incomplete upstream download: {path.name}")
        source_hashes[path.name] = file_hash(path)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        rows.sort(key=lambda row: hashlib.sha256(f"{SEED}:{row['id']}".encode()).hexdigest())
        quotas = {"beginning": 0, "middle": 0, "end": 0}
        for row in rows:
            text, reference = row["context"], row["refered_chunk"]
            start = text.find(reference)
            if not reference.strip() or start < 0 or text.find(reference, start + 1) >= 0:
                exclusions.append({"id": row["id"], "size": size, "reason": "nonunique_span"})
                continue
            depth = start / len(text)
            position = "beginning" if depth < 1 / 3 else "middle" if depth < 2 / 3 else "end"
            question = "".join(char for char in row["query"].casefold() if char.isalnum())
            if quotas[position] >= 4 or question in used_questions:
                continue
            selected.append(
                {
                    "id": row["id"],
                    "size": size,
                    "position": position,
                    "question": row["query"],
                    "answer": row["answer"],
                    "reference": [start, start + len(reference)],
                    "context_chars": len(text),
                    "context_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "upstream_qwen_tokens": row["qwen_length"],
                    "chunk_count": len(chunks(text)),
                }
            )
            used_questions.add(question)
            quotas[position] += 1
        if any(count != 4 for count in quotas.values()):
            raise ValueError(f"insufficient predeclared position quota in {size}: {quotas}")
    return selected, {"source_hashes": source_hashes, "excluded": exclusions}


def freeze(source_dir: Path) -> Path:
    cases, audit = prepare(source_dir)
    directory = Path(".agent-tests/retrieval-benchmarks") / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    texts = sum(case["chunk_count"] + 1 for case in cases)
    if texts > 20000:
        raise ValueError("local encoding budget exceeded before evaluation")
    plan = {
        "run_id": directory.name,
        "protocol": "clongeval-story-reference-span-v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "code_sha256": code_hash(),
        "source": SOURCE,
        "source_revision": REVISION,
        "source_dir": str(source_dir.resolve()),
        **audit,
        "cases": cases,
        "seed": SEED,
        "modes": ["fts", "bge"],
        "window_chars": WIDTH,
        "overlap_chars": OVERLAP,
        "max_tokens": 2500,
        "max_characters": 12000,
        "turn_limit": 6,
        "max_queries": 2 * len(cases),
        "local_embedding_texts": texts,
        "max_local_embedding_texts": 20000,
        "timeout_seconds": 1800,
        "remote_model_calls": 0,
        "automatic_retries": 0,
        "config": load_config().model_dump(mode="json"),
        "python": platform.python_version(),
        "notes": [
            "12 questions per upstream length band; 4 per reference-position third; "
            "fixed SHA order.",
            "Official reference passage, located by unique literal match before retrieval.",
            "Index only fixed-width raw context windows, without query/answer/reference metadata.",
            "Fiction remains fiction. Public archive chunks are not native user biography.",
            "Coverage is union of non-whitespace reference characters in rendered retrieved spans.",
            "A reference paragraph can include irrelevant text; coverage is not answer accuracy.",
            "No model extraction, generation, HTTP, remote calls or official benchmark QA score.",
            "This adapter chunks a supplied corpus; "
            "it does not test the application's file importer.",
            "Timings exclude index construction/model load, include query encoding and recall.",
        ],
    }
    write_json(directory / "protocol.json", plan)
    print(
        json.dumps(
            {
                "event": "frozen",
                "run_id": directory.name,
                "questions": len(cases),
                "local_embedding_texts": texts,
                "sha256": file_hash(directory / "protocol.json"),
            }
        )
    )
    return directory / "protocol.json"


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    done = [row for row in rows if row["status"] == "completed"]
    return {
        "n": len(rows),
        "completed": len(done),
        "failed": len(rows) - len(done),
        "metrics": {
            str(k): {
                metric: sum(row["metrics"][str(k)][metric] for row in rows) / len(rows)
                for metric in ("coverage", "any_reference", "half_reference", "full_reference")
            }
            for k in (1, 3, 6)
        }
        if rows
        else {},
        "total_ms": distribution([row["total_ms"] for row in done]),
        "retrieval_ms": distribution([row["retrieval_ms"] for row in done]),
        "budget_exhausted": sum(bool(row.get("budget_exhausted")) for row in rows),
        "returned_count": distribution([float(len(row["retrieved"])) for row in done]),
    }


def run(path: Path) -> int:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan["code_sha256"] != code_hash():
        raise ValueError("code differs from frozen protocol")
    directory = path.parent
    if (directory / "results.json").exists():
        raise ValueError("refusing to repeat or overwrite this batch")
    sources = {}
    for filename, expected_hash in plan["source_hashes"].items():
        source_path = Path(plan["source_dir"]) / filename
        if file_hash(source_path) != expected_hash:
            raise ValueError("source differs from frozen protocol")
        sources[filename] = {
            row["id"]: row
            for row in map(json.loads, source_path.read_text(encoding="utf-8").splitlines())
        }
    result: dict[str, Any] = {
        "run_id": plan["run_id"],
        "status": "running",
        "errors": [],
        "summaries": {},
    }
    rows: list[dict[str, Any]] = []
    write_json(directory / "results.json", result)
    deadline = time.monotonic() + plan["timeout_seconds"]
    args = argparse.Namespace(
        bge_cache=Path(".agent-data/embeddings"), runtime_dir=Path(".agent-data/embeddings/runtime")
    )
    try:
        for mode in plan["modes"]:
            encoder, space = encoder_for(mode, args)
            for number, case in enumerate(plan["cases"]):
                source = sources[f"clongeval_story_{case['size']}.jsonl"][case["id"]]
                text = source["context"]
                if hashlib.sha256(text.encode()).hexdigest() != case["context_sha256"]:
                    raise ValueError("context mismatch")
                spans = chunks(text, plan["window_chars"], plan["overlap_chars"])
                config = load_config()
                database = Database(directory / mode / str(number), config)
                database.initialize()
                memory = ApplicationMemory(MemoryStore(database), config)
                memory.configure(
                    CognitionSettings(extract_memory=False, embedding_backend="off"),
                    offline=True,
                    model=DeepSeekConfig(),
                    key=None,
                )
                scope = MemoryScope(
                    companion_id="archive", relationship_id="fiction", conversation_id="source"
                )
                now = datetime(2024, 1, 1, tzinfo=UTC)
                ids: dict[str, tuple[int, int]] = {}
                index_started = time.perf_counter()
                for offset in range(0, len(spans), 16):
                    if time.monotonic() > deadline:
                        raise TimeoutError("frozen batch time budget exhausted")
                    batch = spans[offset : offset + 16]
                    vectors = (
                        encoder([text[left:right] for left, right in batch]) if encoder else None
                    )
                    with database.session():
                        for index, (left, right) in enumerate(batch):
                            saved = memory.append_turn(
                                ConversationTurnInput(
                                    user_id="archive-reader",
                                    scope=scope,
                                    actor_id="archive-reader",
                                    role=ConversationRole.USER,
                                    content=text[left:right],
                                    consent=ConsentState.GRANTED,
                                    occurred_at=now,
                                    source_ref=f"clongeval:{case['id']}:{left}:{right}",
                                    metadata={"process_reality_layer": "fiction"},
                                    speech_spans=[
                                        SpeechSpan(
                                            start_offset=0,
                                            end_offset=right - left,
                                            quote_depth=1,
                                            attributed_speaker_id="public-fiction",
                                            reality_layer=RealityLayer.FICTION,
                                            machine_generated=False,
                                        )
                                    ],
                                    embedding=vectors[index] if vectors else None,
                                    embedding_space=space,
                                )
                            )
                            assert saved.stored and saved.turn
                            ids[saved.turn.id] = (left, right)
                row = {**case, "mode": mode, "index_seconds": time.perf_counter() - index_started}
                retrieved = []
                start = time.perf_counter()
                try:
                    if time.monotonic() > deadline:
                        raise TimeoutError("frozen batch time budget exhausted")
                    vector = encoder([case["question"]])[0] if encoder else None
                    encoded = time.perf_counter()
                    with database.session():
                        context = memory.recall(
                            RecallRequest(
                                user_id="archive-reader",
                                scope=scope,
                                query=case["question"],
                                as_of=now + timedelta(days=1),
                                include_turn_evidence=True,
                                state_reality_layer=RealityLayer.FICTION,
                                answer_cardinality=AnswerCardinality.OPEN,
                                turn_limit=plan["turn_limit"],
                                max_tokens=plan["max_tokens"],
                                max_characters=plan["max_characters"],
                                query_embedding=vector,
                                embedding_space=space,
                            )
                        )
                    finished = time.perf_counter()
                    retrieved = [ids[item.turn.id] for item in context.turn_fallback]
                    row.update(
                        status="completed",
                        total_ms=(finished - start) * 1000,
                        retrieval_ms=(finished - encoded) * 1000,
                        budget_exhausted=context.budget_exhausted,
                        rendered_tokens=context.rendered_tokens,
                        sources=[
                            {
                                "span": ids[item.turn.id],
                                "text": item.evidence_text,
                                "reasons": item.reasons,
                            }
                            for item in context.turn_fallback
                        ],
                    )
                except Exception as error:
                    row.update(status="failed", error_type=type(error).__name__, error=str(error))
                row["retrieved"] = retrieved
                row["metrics"] = {
                    str(k): span_metrics(text, tuple(case["reference"]), retrieved[:k])
                    for k in (1, 3, 6)
                }
                with (directory / "queries.jsonl").open("a", encoding="utf-8") as output:
                    output.write(json.dumps(row, ensure_ascii=False) + "\n")
                rows.append(row)
                mode_rows = [item for item in rows if item["mode"] == mode]
                result["summaries"][mode] = summarize(mode_rows)
                result["summaries"][mode]["by_size"] = {
                    size: summarize([item for item in mode_rows if item["size"] == size])
                    for size in SIZES
                }
                result["summaries"][mode]["by_position"] = {
                    pos: summarize([item for item in mode_rows if item["position"] == pos])
                    for pos in ("beginning", "middle", "end")
                }
                write_json(directory / "results.json", result)
                print(
                    json.dumps(
                        {
                            "event": "case_finished",
                            "mode": mode,
                            "case": number + 1,
                            "status": row["status"],
                        }
                    ),
                    flush=True,
                )
        result["status"] = (
            "completed"
            if len(rows) == plan["max_queries"]
            and all(row["status"] == "completed" for row in rows)
            else "failed"
        )
    except Exception as error:
        result["status"] = "failed"
        result["errors"].append({"type": type(error).__name__, "message": str(error)})
    finally:
        result.update(
            executed_queries=len(rows),
            planned_queries=plan["max_queries"],
            code_unchanged=code_hash() == plan["code_sha256"],
            remote_model_calls=0,
            finished_at=datetime.now(UTC).isoformat(),
        )
        write_json(directory / "results.json", result)
        print(
            json.dumps({"event": "finished", "run_id": plan["run_id"], "status": result["status"]})
        )
    return 0 if result["status"] == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir", type=Path, default=Path(".agent-tests/recall-benchmark-sources")
    )
    parser.add_argument("--run", type=Path)
    args = parser.parse_args()
    if args.run:
        return run(args.run)
    freeze(args.source_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
