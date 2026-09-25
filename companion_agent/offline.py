"""An explicit deterministic demo provider. It never opens a network connection."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from companion_agent.automation.loop import ModelStep, ToolCall
from companion_agent.context import ChatMessage
from companion_agent.llm import ModelResponse
from companion_agent.memory_language import forget_target
from companion_memoryos.diagnostics import model_call


class OfflineModel:
    name = "offline-demo-v1"

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        step = self.generate_step([message.model_dump() for message in messages], [], 30)
        return ModelResponse(text=step.text, model=self.name)

    def generate_step(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float
    ) -> ModelStep:
        with model_call(
            "offline", {"model": self.name, "messages": messages, "tools": tools}, live=False
        ) as call:
            result = self._generate_step(messages, tools, timeout)
            call["response"] = result.model_dump(mode="json")
            return result

    def _generate_step(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], timeout: float
    ) -> ModelStep:
        del timeout
        user = next(
            (
                str(item.get("content", ""))
                for item in reversed(messages)
                if item["role"] == "user"
                and not str(item.get("content", "")).startswith("本地工具记录")
            ),
            "",
        )
        evidence: list[dict[str, Any]] = []
        actions: dict[str, int] = {}
        data = next(
            (
                str(item.get("content", ""))
                for item in messages
                if item["role"] == "user"
                and str(item.get("content", "")).startswith("[APPLICATION CONTEXT]\n")
            ),
            "",
        )
        if data:
            memory_json = data.split("[RELEVANT MEMORY]\n", 1)[1].split(
                "\n\n[CONVERSATION ATTRIBUTION]", 1
            )[0]
            memory_data = json.loads(memory_json)
            evidence = memory_data.get("evidence", [])
            for guidance in memory_data.get("guidance", []):
                if guidance.startswith("application_memory:"):
                    actions = json.loads(guidance.split(":", 1)[1])
        memory_question = any(word in user for word in ("记得", "叫什么", "喝什么", "喜欢什么"))
        result = next((item for item in reversed(messages) if item["role"] == "tool"), None)
        if result:
            payload = json.loads(result["content"])
            text = (
                "提醒已经保存，服务运行时会在约定时间通知你。"
                if (payload.get("status") == "succeeded" and payload.get("job_id"))
                else "工具返回的结果：" + json.dumps(payload, ensure_ascii=False)[:1500]
            )
        elif any(
            item["role"] == "user"
            and str(item.get("content", "")).startswith("本地工具记录（continuation：")
            for item in messages[:-1]
        ):
            text = "已收到确认后的成功执行记录，这次操作已完成，可以在能力面板查看结果。"
        elif "待关心的事件资料" in user:
            text = "想起你之前提过的那件事。现在感觉怎么样？愿意的时候再和我聊就好。"
        elif re.fullmatch(r"(?:请)?(?:在)?(\d{1,4})\s*分钟后提醒(?:我)?(.+)", user):
            match = re.fullmatch(r"(?:请)?(?:在)?(\d{1,4})\s*分钟后提醒(?:我)?(.+)", user)
            if match and any(tool["function"]["name"] == "schedule_create" for tool in tools):
                args = {
                    "title": "你安排的小提醒",
                    "message": match[2].strip()[:2000],
                    "at": (datetime.now(UTC) + timedelta(minutes=int(match[1]))).isoformat(),
                }
                call = ToolCall(
                    id="demo-reminder",
                    name="schedule_create",
                    arguments=json.dumps(args, ensure_ascii=False),
                )
                return ModelStep(
                    model=self.name,
                    calls=[call],
                    message={
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": call.id,
                                "type": "function",
                                "function": {
                                    "name": call.name,
                                    "arguments": call.arguments,
                                },
                            }
                        ],
                    },
                )
            text = "可以先开启能力面板中的工具循环，再说“5 分钟后提醒我喝水”。"
        elif forget_target(user) is not None:
            text = (
                "好，这件事以后不再带进聊天里。"
                if actions.get("forgotten", 0)
                else "这句话还没对应到具体记忆，我暂时没有改动已有内容。"
            )
        elif "先听我讲" in user or "少说教" in user:
            text = "好，先听你说。我会把建议放慢一点，你按自己的节奏讲。"
        elif "取消" in user or "别问" in user:
            text = "收到，先不追问。你想再聊的时候再说。"
        elif any(word in user for word in ("紧张", "面试", "难过", "累")):
            text = "听起来这件事让你有些绷着。先陪你待一会儿，你可以接着说。"
        elif not memory_question and actions.get("learned", 0):
            text = "好，记住了，以后按你现在的喜好来。"
        elif memory_question:
            # Show only evidence already selected by the real context builder.
            matches = [
                item["data"]["content"]
                for item in evidence
                if item.get("kind") == "memory"
                and item.get("use_mode") == "explicit_recall"
                and item.get("data", {}).get("status") == "active"
            ]
            text = (
                "我记得你说过：“" + matches[-1] + "”。"
                if matches
                else "这件事我暂时没有可靠的记忆。"
            )
            if not matches:
                tentative = [
                    item["data"]["content"]
                    for item in evidence
                    if item.get("kind") == "memory"
                    and item.get("use_mode") == "soft_reference"
                    and item.get("data", {}).get("status") == "active"
                ]
                if tentative:
                    text = "我印象里你提过：“" + tentative[-1] + "”。"
        else:
            text = "我在听。今天想和我分享哪件小事？"
        return ModelStep(model=self.name, text=text, message={"role": "assistant", "content": text})
