"""Count the actual adapter envelope, including media instructions and tool schemas."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import tiktoken

from companion_agent.automation.loop import AgentLoop, ModelStep, ToolCall
from companion_agent.context import ChatMessage
from companion_agent.llm import ModelResponse
from tests.test_agent_automation import hub_at
from tests.test_romance_app import client_for, configure, message


class CaptureToolModel:
    def __init__(self):
        self.requests: list[dict[str, Any]] = []

    def generate(self, messages: list[ChatMessage]) -> ModelResponse:
        return ModelResponse(text="收到。", model="recording")

    def generate_step(self, messages, tools, timeout):
        self.requests.append(deepcopy({"messages": messages, "tools": tools}))
        return ModelStep(
            message={"role": "assistant", "content": "收到。"}, text="收到。", model="recording"
        )


def test_real_application_counts_media_and_tools_before_allocating_history(tmp_path: Path):
    model = CaptureToolModel()
    client = client_for(tmp_path, model)
    configure(client)
    history = []
    for index in range(18):
        content = f"第 {index} 段材料。" + "窗外的银杏在风中摇摆，走廊尽头的灯亮着。" * 40
        history.append(content)
        response = client.post("/api/chat", json=message(client, content, f"long-{index}"))
        assert response.status_code == 200, response.text
        actual = model.requests[-1]
        assert actual["messages"][-1]["content"] == content
        tokens = len(
            tiktoken.get_encoding("cl100k_base").encode(json.dumps(actual, ensure_ascii=False))
        )
        assert tokens <= 16000, (index, tokens)
        assert actual["tools"]
        assert "媒体输出" in json.dumps(actual["messages"], ensure_ascii=False)
    assert len(model.requests) == len(history)  # Previewing may not call the provider.


def test_tool_result_growth_stops_before_a_second_overflowing_model_request(tmp_path, monkeypatch):
    hub, _, _ = hub_at(tmp_path)
    invoked = []

    def invoke(*args):
        invoked.append(args)
        return {"status": "succeeded", "data": "工具返回内容。" * 2000}

    monkeypatch.setattr(hub, "invoke", invoke)

    class ToolResultModel(CaptureToolModel):
        def generate_step(self, messages, tools, timeout):
            super().generate_step(messages, tools, timeout)
            call = ToolCall(id="one", name="local_time", arguments="{}")
            return ModelStep(
                message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "one",
                            "type": "function",
                            "function": {"name": "local_time", "arguments": "{}"},
                        }
                    ],
                },
                calls=[call],
                model="recording",
            )

    model = ToolResultModel()
    loop = AgentLoop(model, hub, max_context_tokens=3500)
    with loop.run("c", "bounded") as run:
        response = loop.generate([ChatMessage(role="user", content="请查看本地时间。")])
    assert len(model.requests) == len(invoked) == 1
    assert run.status == "limited"
    assert "上下文" in response.text


def test_input_that_cannot_fit_is_reported_without_calling_or_truncating(tmp_path):
    model = CaptureToolModel()
    client = client_for(tmp_path, model)
    configure(client)
    host = client.app.state.host
    content = "测试内容。" * 1000
    host.agent.max_context_tokens = 1000
    payload = message(client, content, "oversized")
    failed = client.post("/api/chat", json=payload)
    assert failed.status_code == 422
    assert failed.json()["detail"]["code"] == "context_budget_exceeded"
    assert not model.requests
    history = client.get(f"/api/conversations/{payload['conversation_id']}/messages").json()
    assert [m["content"] for m in history["messages"]] == [content]
    streamed = client.post("/api/chat/stream", json=payload)
    events = [json.loads(line) for line in streamed.text.splitlines()]
    assert events[-1]["type"] == "done"
    assert any(e.get("code") == "context_budget_exceeded" for e in events)
    assert not model.requests
    host.agent.max_context_tokens = 16000
    assert (
        client.post("/api/chat", json=message(client, "这次先聊一句。", "next")).status_code == 200
    )
