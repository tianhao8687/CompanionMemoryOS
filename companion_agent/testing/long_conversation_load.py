"""Bounded real-process long dialogue and long-message evidence checks, offline only.

Every source is written through ordinary HTTP chat. Expected answers/IDs are used
only by the external scorer. Results concern final model inputs, never generated QA.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from companion_agent.testing.adaptive_context_benchmark import evidence_from_messages
from companion_agent.testing.control import is_local_embedding_url
from companion_agent.testing.driver import DriverError, ManagedInstance
from companion_agent.testing.memory_load import latency
from companion_agent.testing.retrieval_benchmark import write_json
from companion_memoryos.tokens import TiktokenTokenCounter


def corpus(turns: int, seed: int, long_chars: int = 4800) -> list[dict[str, Any]]:
    rows = []
    padding = "窗外的银杏在风中摇摆，走廊尽头的灯亮着。"
    ordinary = [
        "今天整理书架时，先按大小摆好书，再把空纸箱收到门边。",
        "傍晚在小区散步，路上有几只麻雀，树下也有不少落叶。",
        "厨房的台面已经擦干净，晾着的杯子和盘子也都归位了。",
        "阳台的花盆换了位置，靠窗留出一块地方看下午的阳光。",
    ]
    for index in range(turns):
        row: dict[str, Any] = {"index": index}
        if index < 3 or index % 100 == 99:
            digest = hashlib.sha256(f"{seed}:{index}".encode()).hexdigest()
            row.update(key="LC" + digest[:10], value="柜" + digest[12:20])
            fact = f"档案 {row['key']} 的封套保管位置是{row['value']}。"
            if index < 3:
                background = (padding * 400)[:long_chars]
                offset = (0, len(background) // 2, len(background))[index]
                row.update(position=("beginning", "middle", "end")[index])
                row["content"] = background[:offset] + fact + background[offset:]
            else:
                row["content"] = fact + ordinary[index % len(ordinary)] * 10
        else:
            row["content"] = f"这是第 {index + 1} 次生活记录。" + ordinary[index % 4] * 24
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--turns", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--long-chars", type=int, default=4800)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--embedding-mode", choices=["fts", "hash", "local-api"], default="fts")
    parser.add_argument("--local-embedding-url")
    parser.add_argument("--embedding-model", default="BAAI/bge-small-zh-v1.5")
    args = parser.parse_args()
    if not 100 <= args.turns <= 800 or args.turns % 100:
        parser.error("turns must be a multiple of 100 between 100 and 800")
    if not 1000 <= args.long_chars <= 5800:
        parser.error("long-chars must be between 1000 and 5800")
    local_api = args.embedding_mode == "local-api"
    if local_api and not is_local_embedding_url(args.local_embedding_url or ""):
        parser.error("local-api requires --local-embedding-url http://127.0.0.1:<port>/v1")
    if not local_api and args.local_embedding_url:
        parser.error("local-embedding-url requires embedding-mode local-api")
    plan = corpus(args.turns, args.seed, args.long_chars)
    instance = ManagedInstance(
        Path(".agent-tests"),
        allow_live=False,
        max_turns=args.turns + 100,
        max_calls=args.turns * 6 + 200 if local_api else args.turns + 150,
        timeout=args.timeout,
        local_embedding_url=args.local_embedding_url,
    )
    counter = TiktokenTokenCounter("cl100k_base")
    result: dict[str, Any] = {
        "run_id": instance.run_id,
        "status": "running",
        "checks": [],
        "phases": [],
        "layer": "offline HTTP, persisted sources and final model input; no language scoring",
        "embedding_mode": args.embedding_mode,
    }
    write_json(
        instance.directory / "long-protocol.json",
        {
            "seed": args.seed,
            "long_chars": args.long_chars,
            "turns": plan,
            "checkpoints": list(range(100, args.turns + 1, 100)),
            "restart_every": 200,
            "context_limit": 16000,
            "remote_calls": 0,
            "embedding_mode": args.embedding_mode,
            "embedding_model": args.embedding_model if local_api else None,
            "acceptance": "no lost acknowledged writes; full current input; correct evidence and "
            "source IDs at every checkpoint; no superseded/forgotten preference; "
            "bounded model input",
        },
    )
    print(json.dumps({"event": "started", "run_id": instance.run_id}), flush=True)
    rows_path = instance.directory / "long-requests.jsonl"
    sources: list[dict[str, Any]] = []
    acknowledged: set[str] = set()
    intentionally_removed: set[str] = set()
    http_times: list[float] = []
    audit_times: list[float] = []
    context_sizes: list[float] = []
    phase_start = 0

    def save() -> None:
        write_json(instance.directory / "long-results.json", result)

    def check(label: str, passed: bool, **details: Any) -> None:
        result["checks"].append({"label": label, "passed": passed, **details})
        save()

    try:
        client = instance.start()
        result["code"] = client.identity["code"]
        settings = client.request("GET", "/api/bootstrap")["settings"]
        settings["cognition"].update(
            embedding_backend={"fts": "off", "hash": "local", "local-api": "local_api"}[
                args.embedding_mode
            ]
        )
        if local_api:
            settings["cognition"]["embedding"].update(
                base_url=args.local_embedding_url, model=args.embedding_model
            )
        client.request("PUT", "/api/settings", {"settings": settings})
        conversation = client.new_session()
        result["conversation_id"] = conversation

        def chat_request(response: dict[str, Any]) -> dict[str, Any]:
            # Background embedding completions can arrive after the main call.
            return next(
                c["request"]
                for c in reversed(response["trace"]["calls"])
                if "messages" in c["request"]
            )

        def send(content: str, session: str, label: str) -> dict[str, Any]:
            started = time.perf_counter()
            # Separate chat+stream completion from diagnostic/export overhead.
            response: dict[str, Any] = client.request(
                "POST",
                "/api/chat/stream",
                {
                    "conversation_id": session,
                    "content": content,
                    "request_id": "long_" + hashlib.sha256(label.encode()).hexdigest()[:24],
                },
            )
            received = time.perf_counter()
            response["trace"] = client.inspect_trace(response["trace_id"])
            page = client.request("GET", f"/api/conversations/{session}/messages?limit=4")
            model_request = chat_request(response)
            messages = model_request["messages"]
            serialized = json.dumps(
                {
                    "messages": messages,
                    "tools": model_request.get("tools", []),
                },
                ensure_ascii=False,
            )
            tokens = counter.count(serialized)
            checks = {
                "persisted": any(m["id"] == response["assistant"]["id"] for m in page["messages"]),
                "reply_to": response["assistant"]["reply_to"] == response["user"]["id"],
                "current_input_intact": messages[-1]["content"] == content,
                "context_within_limit": tokens <= 16000,
                "no_live_call": all(not c.get("live") for c in response["trace"]["calls"]),
            }
            if local_api:
                checks["semantic_query_encoded"] = any(
                    c["source"] == "embedding"
                    and not c.get("background")
                    and c.get("vector_dimensions", 0) > 0
                    and c["request"].get("model") == args.embedding_model
                    for c in response["trace"]["calls"]
                )
            row: dict[str, Any] = {
                "label": label,
                "content": content,
                "http_ms": (received - started) * 1000,
                "audit_ms": (time.perf_counter() - received) * 1000,
                "context_tokens": tokens,
                "checks": checks,
                "response": response,
            }
            with rows_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            http_times.append(row["http_ms"])
            audit_times.append(row["audit_ms"])
            context_sizes.append(tokens)
            if session == conversation:
                acknowledged.update((response["user"]["id"], response["assistant"]["id"]))
            if not all(checks.values()):
                check(label, False, failed=[key for key, passed in checks.items() if not passed])
            return response

        send("我喜欢咖啡。", conversation, "preference-original")
        state = client.read_state(conversation)
        preference = next(m for m in state["memories"] if "喜欢咖啡" in m["content"])
        settings["cognition"].update(extract_memory=False)
        client.request("PUT", "/api/settings", {"settings": settings})
        current_preference = "我喜欢咖啡"
        corrected_preference = "我不喜欢咖啡了"
        forgotten = False
        for item in plan:
            response = send(item["content"], conversation, f"write-{item['index']}")
            if "key" in item:
                sources.append({**item, "id": response["user"]["id"]})
            count = item["index"] + 1
            if count % 100:
                if count % 25 == 0:
                    print(json.dumps({"event": "progress", "completed_writes": count}), flush=True)
                continue
            if count == 200:
                correction = client.correct_memory(
                    conversation, preference["id"], corrected_preference + "。"
                )
                preference = correction["memory"]
                current_preference = corrected_preference
            if count == 400:
                before_forget = {m["id"] for m in client.read_history(conversation)}
                client.forget_memory(preference["id"])
                after_forget = {m["id"] for m in client.read_history(conversation)}
                intentionally_removed.update(before_forget - after_forget)
                forgotten = True
            if count % 200 == 0:
                before = [m["id"] for m in client.read_history(conversation)]
                client = instance.restart()
                after = [m["id"] for m in client.read_history(conversation)]
                check(f"restart-{count}", before == after, messages=len(after))
            history = client.read_history(conversation)
            visible_ids = {m["id"] for m in history}
            # Forgetting intentionally removes its source, which is not a lost write.
            check(
                f"history-{count}",
                (acknowledged - intentionally_removed <= visible_ids)
                and all(
                    any(m["id"] == s["id"] and m["content"] == s["content"] for m in history)
                    for s in sources
                ),
                messages=len(history),
                acknowledged_present=len(acknowledged & visible_ids),
            )
            query_session = client.new_session()
            for source in [*sources[:3], sources[-1]]:
                query = f"帮我回忆档案 {source['key']} 的封套保管位置。"
                response = send(query, query_session, f"recall-{count}-{source['index']}")
                messages = chat_request(response)["messages"]
                evidence = evidence_from_messages(messages)
                admitted = [e for e in evidence if e.get("id") == source["id"]]
                check(
                    f"source-{count}-{source['index']}",
                    any(source["value"] in str(e.get("content", "")) for e in admitted),
                    source_id=source["id"],
                    position=source.get("position", "short"),
                    gap=count - source["index"],
                    trace_id=response["trace_id"],
                )
            response = send(
                "我现在对饮料的偏好是什么？", client.new_session(), f"preference-{count}"
            )
            messages = chat_request(response)["messages"]
            text = json.dumps(messages, ensure_ascii=False)
            check(
                f"preference-{count}",
                (
                    "咖啡" not in text
                    if forgotten
                    else current_preference in text and (count < 200 or "我喜欢咖啡" not in text)
                ),
                forgotten=forgotten,
                trace_id=response["trace_id"],
            )
            phase = {
                "completed_writes": count,
                "http_ms": latency(http_times[phase_start:]),
                "audit_ms": latency(audit_times[phase_start:]),
                "context_tokens": latency(context_sizes[phase_start:]),
            }
            result["phases"].append(phase)
            phase_start = len(http_times)
            save()
            print(json.dumps({"event": "checkpoint", **phase}), flush=True)
        result.update(
            status="passed" if all(c["passed"] for c in result["checks"]) else "failed",
            requests=len(http_times),
            input_characters=sum(len(r["content"]) for r in plan),
            http_ms=latency(http_times),
            audit_ms=latency(audit_times),
            context_tokens=latency(context_sizes),
            identity=client.request("GET", "/api/testing/discover"),
        )
    except Exception as error:
        result.update(status="failed", error=repr(error))
        if isinstance(error, DriverError):
            result["failure_evidence"] = error.evidence
        raise
    finally:
        instance.stop()
        save()
        print(
            json.dumps(
                {"event": "finished", "run_id": instance.run_id, "status": result["status"]}
            ),
            flush=True,
        )
    return int(result["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
