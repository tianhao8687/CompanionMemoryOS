from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

from companion_agent import CompanionAgent, RelationshipStage, load_persona
from companion_agent.llm import MainLLMError, OpenAICompatibleMainLLM
from companion_memoryos.config import InterpreterConfig, load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import ConsentState, MemoryScope, ProcessTurnRequest, ResponseGoal
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore


def main() -> None:
    parser = argparse.ArgumentParser(description="CompanionAgent stable persona chat host")
    parser.add_argument("--persona", type=Path)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--memory-config", type=Path)
    parser.add_argument("--user", default="user")
    parser.add_argument("--companion", default="xiaohe")
    parser.add_argument("--relationship", default="relationship")
    parser.add_argument("--conversation", default="chat")
    parser.add_argument(
        "--stage", choices=[stage.value for stage in RelationshipStage], default="new"
    )
    parser.add_argument("--goal", choices=[goal.value for goal in ResponseGoal])
    parser.add_argument("--max-persona-tokens", type=int, default=1200)
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--api-key-env", default="MAIN_LLM_API_KEY")
    parser.add_argument("--allow-model", action="store_true")
    parser.add_argument(
        "--prepare", metavar="TEXT", help="compose input locally without a model call"
    )
    args = parser.parse_args()
    if args.prepare is None and (not args.allow_model or not args.base_url or not args.model):
        parser.error(
            "chat requires --allow-model, --base-url and --model; use --prepare for local input"
        )
    config = load_config(args.memory_config)
    database = Database(args.data_dir, config)
    database.initialize()
    # --prepare never invokes even a configured MemoryOS interpreter.
    service = CompanionMemoryService(MemoryStore(database), config)
    llm = (
        OpenAICompatibleMainLLM(
            InterpreterConfig(
                base_url=args.base_url,
                model=args.model,
                api_key_env=args.api_key_env,
            )
        )
        if args.prepare is None
        else None
    )
    agent = CompanionAgent(
        service, load_persona(args.persona), llm, max_persona_tokens=args.max_persona_tokens
    )
    scope = MemoryScope(
        companion_id=args.companion,
        relationship_id=args.relationship,
        conversation_id=args.conversation,
    )

    def request(text: str) -> ProcessTurnRequest:
        return ProcessTurnRequest(
            user_id=args.user,
            scope=scope,
            content=text,
            idempotency_key=str(uuid4()),
            consent=ConsentState.GRANTED,
            calendar_timezone="Asia/Shanghai",
            model_consent=ConsentState.GRANTED if args.prepare is None else ConsentState.DENIED,
        )

    stage = RelationshipStage(args.stage)
    goal = ResponseGoal(args.goal) if args.goal else None
    if args.prepare is not None:
        prepared = agent.prepare(request(args.prepare), stage, response_goal=goal)
        print(
            json.dumps(
                [m.model_dump() for m in prepared.context.messages], ensure_ascii=False, indent=2
            )
        )
        return
    print("输入 /quit 结束；关系阶段由 --stage 指定。")
    while True:
        try:
            content = input("你：").strip()
            if content == "/quit":
                break
            if content:
                try:
                    reply = agent.chat(request(content), stage, response_goal=goal)
                    print(f"{agent.persona.display_name}：{reply.turn.content}")
                except (MainLLMError, ValueError) as error:
                    print(f"本轮未完成：{error}")
        except (EOFError, KeyboardInterrupt):
            break


if __name__ == "__main__":
    main()
