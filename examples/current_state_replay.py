"""Reproducible context/strategy check. No real model or network is used."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from companion_agent import CompanionAgent, load_persona
from companion_agent.context import ChatMessage
from companion_agent.llm import ModelResponse
from companion_agent.relationship import RelationshipKey
from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import ProcessTurnRequest
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore


class ContextOnlyModel:
    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        return ModelResponse(text="本地传输桩，不代表真实模型对话效果。", model="context-only-stub")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    config = load_config()
    database = Database(args.data_dir, config)
    database.initialize()
    agent = CompanionAgent(
        CompanionMemoryService(MemoryStore(database), config),
        load_persona(),
        ContextOnlyModel(),
        recent_turn_limit=1,
    )
    key = RelationshipKey(
        user_id="demo-user", companion_id="xiaohe", relationship_id=f"demo-{uuid4()}"
    )
    messages = [
        "我有点疲惫，别急着给方案，让我把事情说完。",
        "后来又有新的事情发生。",
        "缓过来了，帮我列两个办法。",
        "请解释一下二分查找。",
    ]
    print("仅验证数据、最终上下文与回应策略；不验证真实模型话术。")
    assert agent.current_states is not None
    for index, text in enumerate(messages):
        if index == 3:
            at = datetime.now(UTC) + timedelta(hours=13)
            agent.current_states.clock = lambda at=at: at
        response = agent.chat(
            ProcessTurnRequest.model_validate(
                {
                    "user_id": key.user_id,
                    "scope": {
                        "companion_id": key.companion_id,
                        "relationship_id": key.relationship_id,
                        "conversation_id": "demo",
                    },
                    "content": text,
                    "idempotency_key": str(index),
                    "consent": "granted",
                    "model_consent": "granted",
                    "enable_recall": False,
                }
            )
        )
        print(
            json.dumps(
                {
                    "input": text,
                    "response_goal": response.turn.metadata["response_goal"],
                    "active_state": [
                        {"slot": record.slot, "value": record.value}
                        for record in agent.current_states.snapshot(key, "demo")
                    ],
                    "current_state_tokens": response.turn.metadata["current_state_tokens"],
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
