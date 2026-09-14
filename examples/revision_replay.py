"""Compare the same scenarios across checkouts; stub runs measure engineering, not naturalness."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from companion_agent import CompanionAgent, load_persona
from companion_agent.context import ChatMessage
from companion_agent.llm import MainLLM, ModelResponse, OpenAICompatibleMainLLM
from companion_agent.relationship import RelationshipKey
from companion_memoryos.config import InterpreterConfig, load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import ProcessTurnRequest
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore

SCENARIOS = {
    "negated_complaint": ["你刚才没有打断我，我很感谢你。", "我接着说。"],
    "denied_repair": ["你刚才打断我，让我很不舒服。", "我不能原谅你。", "还有一件事。"],
    "third_party": ["今天我朋友很难过。", "最近我的同事有点累，压力也很大。"],
    "quoted_repair": ["你刚才打断我，让我很不舒服。", "他说“我已经原谅你了”，但我还没有。"],
    "other_repair": ["你刚才打断我，让我很不舒服。", "我和同事的误会说开了，但和你还没有。"],
    "affirmative": ["我今天很难过。", "你刚才误解我，我很生气。", "我已经原谅你了。"],
    "listen_then_solve": [
        "我不是不想听建议，只是想先说完。",
        *[f"还有第{i}件事没讲。" for i in range(4)],
        "现在给我两个办法。",
    ],
    "tired_task": ["我很累，帮我修改这段自我介绍：我做过数据分析，想找产品方面的工作。"],
    "requested_humor": ["我很难过，先听我说。", "讲个笑话让我缓缓。", "接着帮我改一句介绍。"],
    "returning": ["你好，很高兴认识你。", "好久不见！见到你真开心！"],
    "distance": ["以后保持距离吧。", "好久不见！见到你真开心！"],
    "topic_hold": [
        "我担心面试。房租也让我担心。",
        "先别提面试了。",
        "房租也先别提了。",
        "帮我分析工作安排。",
        "现在继续聊面试。",
    ],
    "correction": ["我很难过，也有点累。", "我不是难过，只是累。"],
}


class Recorder:
    def __init__(self, delegate: MainLLM | None) -> None:
        self.delegate = delegate
        self.messages: list[ChatMessage] = []
        self.calls = 0
        self.generation_ms = 0.0

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        self.messages = messages
        self.calls += 1
        started = perf_counter()
        response = (
            self.delegate.generate(messages)
            if self.delegate
            else ModelResponse(text="传输桩：不代表真实模型体验。", model="revision-stub")
        )
        self.generation_ms = (perf_counter() - started) * 1000
        return response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--live-config", type=Path, help="Explicitly authorizes live calls; JSON InterpreterConfig"
    )
    parser.add_argument("--include-context", action="store_true")
    args = parser.parse_args()
    delegate = None
    settings = None
    if args.live_config:
        settings = InterpreterConfig.model_validate_json(
            args.live_config.read_text(encoding="utf-8")
        )
        delegate = OpenAICompatibleMainLLM(settings)
    rows = []
    for scenario, messages in SCENARIOS.items():
        with TemporaryDirectory(prefix="companion-revision-") as directory:
            config = load_config()
            database = Database(Path(directory), config)
            database.initialize()
            memory = CompanionMemoryService(MemoryStore(database), config)
            recorder = Recorder(delegate)
            agent = CompanionAgent(memory, load_persona(), recorder, recent_turn_limit=1)
            key = RelationshipKey(
                user_id="replay-user", companion_id="xiaohe", relationship_id=scenario
            )
            for index, text in enumerate(messages):
                at = datetime.now(UTC)
                if index == 0 and scenario in {"returning", "distance"}:
                    at -= timedelta(days=60)
                before_calls = recorder.calls
                started = perf_counter()
                response = agent.chat(
                    ProcessTurnRequest.model_validate(
                        {
                            "user_id": key.user_id,
                            "scope": {
                                "companion_id": key.companion_id,
                                "relationship_id": scenario,
                                "conversation_id": "replay",
                            },
                            "content": text,
                            "idempotency_key": str(index),
                            "occurred_at": at,
                            "consent": "granted",
                            "model_consent": "granted",
                            "enable_recall": False,
                        }
                    )
                )
                elapsed = (perf_counter() - started) * 1000
                source = memory.get_turn_interpretation(
                    response.turn.reply_to_turn_id or "", key.user_id
                )
                rows.append(
                    {
                        "scenario": scenario,
                        "turn": index,
                        "input": text,
                        "output": response.turn.content,
                        "model": response.turn.metadata["model"],
                        "response_goal": response.turn.metadata["response_goal"],
                        "distance": response.turn.metadata["relationship_distance"],
                        "conflict": agent.relationships.get_relationship(
                            key
                        ).recent_dynamics.recent_conflict_level,
                        "states": [
                            {"slot": r.slot, "value": r.value, "topic": r.topic}
                            for r in agent.current_states.snapshot(key, "replay")
                        ]
                        if agent.current_states
                        else [],
                        "latency_ms": round(elapsed, 2),
                        "generation_ms": round(recorder.generation_ms, 2),
                        "main_calls": recorder.calls - before_calls,
                        "provider_calls": recorder.calls - before_calls if delegate else 0,
                        "interpreter_calls": 0 if memory.turn_interpreter is None else None,
                        "interpreter_configured": memory.turn_interpreter is not None,
                        "interpretation_status": "recorded" if source else "not_configured",
                        "context_tokens": memory.token_counter.count(
                            json.dumps(
                                [m.model_dump() for m in recorder.messages], ensure_ascii=False
                            )
                        ),
                        "usage": response.turn.metadata.get("usage"),
                        **(
                            {"messages": [m.model_dump() for m in recorder.messages]}
                            if args.include_context
                            else {}
                        ),
                    }
                )
    report = {
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "worktree_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        ),
        "mode": "live" if delegate else "stub",
        "live_model_executed": bool(delegate),
        "experience_verified": False,  # Requires a separate review of the recorded conversations.
        "sampling": "same adapter and provider defaults; compare with identical provider config",
        "provider_model": settings.model if settings else None,
        "python": platform.python_version(),
        "tools": {name: version(name) for name in ("ruff", "mypy", "pytest", "tiktoken")},
        "source_digest": hashlib.sha256(
            b"".join(
                path.as_posix().encode() + path.read_text(encoding="utf-8").encode()
                for package in (Path("companion_agent"), Path("companion_memoryos"))
                for path in sorted(package.rglob("*"))
                if path.is_file() and path.suffix in {".py", ".yaml", ".toml"}
            )
        ).hexdigest(),
        "median_latency_ms": statistics.median(r["latency_ms"] for r in rows),
        "median_context_tokens": statistics.median(r["context_tokens"] for r in rows),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
