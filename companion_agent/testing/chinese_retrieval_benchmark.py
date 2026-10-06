"""Offline PerLTQA Chinese source-document retrieval, not generated QA accuracy.

Uses official reference IDs and complete source documents. It is intentionally
separate from turn-level chat benchmarks: one dialogue document has many turns.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4

from companion_agent.testing.retrieval_benchmark import (
    encoder_for,
    evaluate_sample,
    summarize,
    write_json,
)
from companion_memoryos.config import load_config

SOURCE_COMMIT = "8d9e19868e239740ef701e603ec205cd581f221b"
SOURCE_HASHES = {
    "perltmem.json": "5869ee39e944cf835af5c163c5213723bd2d30c44eb6705271031a644ee0ab7b",
    "perltqa.json": "aa19a0623312b5ffe1153ee5d04e20e0d054ba27eccc4f35baa9710a6e8ca9bd",
}
# These two people were inspected while implementing the schema adapter.
DEVELOPMENT_PEOPLE = {"张小红", "王小明"}
SEED = "20260929"


def dialogue_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(dialogue_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(str(key) + "\n" + dialogue_text(item) for key, item in value.items())
    raise ValueError("unsupported dialogue source structure")


def reference_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        if value.startswith("["):
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError):
                return []
        else:
            value = [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return []
    return sorted(set(value))


def prepare_samples(
    memories: list[dict[str, Any]],
    questions: list[dict[str, Any]],
    *,
    split: str,
    exclude_ids: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    people = {item["profile"]["Protagonist"]: item for item in memories}
    if len(people) != len(memories):
        raise ValueError("ambiguous duplicate protagonist")
    samples, audits = [], []
    for entry in questions:
        for name, sections in entry.items():
            if (name in DEVELOPMENT_PEOPLE) != (split == "development"):
                continue
            person = people[name]
            docs = {"profile": person["profile_description"]}
            docs.update(
                {
                    key: json.dumps(value, ensure_ascii=False)
                    for key, value in person["social_relationship"].items()
                }
            )
            docs.update({key: value["content"] for key, value in person["events"].items()})
            docs.update(
                {
                    key: dialogue_text(value["contents"])
                    for key, value in person["dialogues"].items()
                }
            )
            chosen = []
            for category, section in enumerate(("events", "dialogues"), 1):
                eligible, excluded = [], []
                for group, rows in sections[section].items():
                    for index, row in enumerate(rows):
                        identifier = f"{name}:{section}:{group}:{index}"
                        if exclude_ids and identifier in exclude_ids:
                            excluded.append({"id": identifier, "reason": "previously_evaluated"})
                            continue
                        gold = reference_ids(row.get("Reference Memory"))
                        if not gold or not set(gold).issubset(docs):
                            excluded.append({"id": identifier, "reason": "unresolvable_reference"})
                            continue
                        eligible.append(
                            {
                                "source_question_id": identifier,
                                "question": row["Question"],
                                "evidence": gold,
                                "category": category,
                            }
                        )
                eligible.sort(
                    key=lambda row: hashlib.sha256(
                        (SEED + row["source_question_id"]).encode()
                    ).hexdigest()
                )
                selected = eligible[:10]
                chosen.extend(selected)
                audits.append(
                    {
                        "person": name,
                        "section": section,
                        "eligible": len(eligible),
                        "excluded": excluded,
                        "selected_ids": [row["source_question_id"] for row in selected],
                    }
                )
            sample_id = hashlib.sha256(name.encode()).hexdigest()[:12]
            samples.append(
                {
                    "sample_id": sample_id,
                    "person": name,
                    "conversation": {
                        "session_1_date_time": "12:00 PM on 01 January, 2024",
                        "session_1": [
                            {"dia_id": key, "speaker": name, "text": value}
                            for key, value in docs.items()
                        ],
                    },
                    "qa": chosen,
                }
            )
    return samples, audits


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--split", choices=("development", "holdout"), default="holdout")
    parser.add_argument("--label", required=True)
    parser.add_argument("--exclude-protocol", type=Path)
    parser.add_argument(
        "--modes", nargs="+", choices=("fts", "hash", "bge"), default=["fts", "hash", "bge"]
    )
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--bge-cache", type=Path, default=Path(".agent-data/embeddings"))
    parser.add_argument("--runtime-dir", type=Path)
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("timeout must be positive")
    data = {}
    for filename, expected in SOURCE_HASHES.items():
        raw = (args.source_dir / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            parser.error(f"{filename} differs from the pinned upstream source")
        data[filename] = json.loads(raw)
    excluded_ids: set[str] = set()
    excluded_protocol_hash = None
    if args.exclude_protocol:
        previous = args.exclude_protocol.read_bytes()
        previous_plan = json.loads(previous)
        if previous_plan.get("protocol") != "perltqa-zh-source-document-v1":
            parser.error("exclusion requires a PerLTQA selection protocol")
        if previous_plan.get("source_hashes") != SOURCE_HASHES:
            parser.error("exclusion protocol must use the same pinned source")
        for selection in previous_plan["selection"]:
            ids = selection["selected_ids"]
            if not isinstance(ids, list) or not all(isinstance(item, str) for item in ids):
                parser.error("invalid exclusion IDs")
            excluded_ids.update(ids)
        excluded_protocol_hash = hashlib.sha256(previous).hexdigest()
    samples, audits = prepare_samples(
        data["perltmem.json"], data["perltqa.json"], split=args.split, exclude_ids=excluded_ids
    )
    texts = sum(len(sample["conversation"]["session_1"]) + len(sample["qa"]) for sample in samples)
    if texts > 10000:
        parser.error("local embedding text budget exceeded")
    directory = Path(".agent-tests/retrieval-benchmarks") / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    fingerprint = hashlib.sha256()
    for path in sorted(
        [*Path("companion_agent").rglob("*.py"), *Path("companion_memoryos").rglob("*.py")]
    ):
        fingerprint.update(path.as_posix().encode() + b"\0" + path.read_bytes())
    plan = {
        "run_id": directory.name,
        "label": args.label,
        "split": args.split,
        "protocol": "perltqa-zh-source-document-v1",
        "source_commit": SOURCE_COMMIT,
        "source_hashes": SOURCE_HASHES,
        "code_sha256": fingerprint.hexdigest(),
        "selection": audits,
        "excluded_protocol_sha256": excluded_protocol_hash,
        "excluded_question_ids": sorted(excluded_ids),
        "seed": SEED,
        "config": load_config().model_dump(mode="json"),
        "timeout_seconds": args.timeout,
        "local_texts_per_encoder": texts,
        "remote_model_calls": 0,
        "automatic_retries": 0,
        "notes": [
            "Up to 10 event and 10 dialogue questions per person, SHA256 order; "
            "30 held-out people.",
            "Official reference memory IDs; no answers or anchors enter the index.",
            "Each full source document is a user-supplied archive turn, "
            "not a native chat utterance.",
            "All profile/relationship/event/dialogue sources for that person are searchable.",
            "Documents retain literal source dates; synthetic import time is 2024-01-01 UTC.",
            "Queries use one day after import; this is not a temporal-accuracy benchmark.",
            "Scoring is after the normal 6-turn/2500-token/12000-character prompt budget.",
            "No extraction, generation, remote model calls, HTTP or concurrent load.",
            "BGE uses existing CPU cache directly with 512-token truncation.",
        ],
    }
    write_json(directory / "protocol.json", plan)
    result: dict[str, Any] = {
        "run_id": directory.name,
        "label": args.label,
        "status": "running",
        "summaries": {},
        "samples": [],
        "errors": [],
    }
    print(
        json.dumps(
            {
                "event": "started",
                "run_id": directory.name,
                "questions": sum(len(sample["qa"]) for sample in samples),
            }
        ),
        flush=True,
    )
    deadline = time.monotonic() + args.timeout
    try:
        for mode in dict.fromkeys(args.modes):
            rows = []
            encoder, space = encoder_for(mode, args)
            for sample in samples:
                sample_rows, info = evaluate_sample(
                    directory, sample, mode, encoder, space, None, deadline
                )
                rows.extend(sample_rows)
                result["samples"].append(info)
                result["summaries"][mode] = summarize(rows)
                write_json(directory / "results.json", result)
            result["summaries"][mode]["categories"] = {
                category: summarize([row for row in rows if row["category"] == index])
                for index, category in enumerate(("events", "dialogues"), 1)
            }
            result["summaries"][mode]["returned_counts"] = dict(
                Counter(len(row["retrieved"]) for row in rows)
            )
            # Do not reveal held-out scores while the production fix is still being developed.
            print(
                json.dumps({"event": "mode_finished", "mode": mode, "questions": len(rows)}),
                flush=True,
            )
        result["status"] = (
            "failed" if any(s["failed"] for s in result["summaries"].values()) else "completed"
        )
    except Exception as exc:
        result["status"] = "failed"
        result["errors"].append({"type": type(exc).__name__, "message": str(exc)})
    finally:
        write_json(directory / "results.json", result)
    print(
        json.dumps(
            {
                "event": "finished",
                "run_id": directory.name,
                "status": result["status"],
                "errors": result["errors"],
            }
        ),
        flush=True,
    )
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
