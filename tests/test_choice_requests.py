"""Delegated choices use the current task path without creating an action grant."""

from pathlib import Path

import pytest

from companion_agent.app import LOCAL_USER
from companion_agent.current_state.evaluator import analyze_current_turn
from companion_agent.memory_lifecycle import is_conversation_task
from companion_agent.task_intent import is_choice_request
from tests.test_romance_app import RecordingLLM, client_for, configure, message


@pytest.mark.parametrize(
    "text",
    [
        "给我选部悬疑片吧，别恐怖，我怕。",
        "你挑一个，我今天不想再做选择了。",
        "帮我给妈妈挑个礼物。",
        "请推荐三本书，我想比较一下。",
        "你从这两件里选一件。",
        "帮我挑一部明天看的电影。",
        "你就挑一部我晚点看，我去回我妈电话了。",
    ],
)
def test_current_choices_are_tasks_in_both_context_paths(text: str) -> None:
    assert is_choice_request(text)
    assert is_conversation_task(text)
    assert analyze_current_turn(text).concrete_task


@pytest.mark.parametrize(
    "text",
    [
        "不要给我推荐电影。",
        "你别帮我选。",
        "你不用给我推荐书。",
        "你给我别选了。",
        "请给妈妈不要推荐首饰。",
        "她说：给我选部电影。",
        "她发了句“你帮我选一件吧”。",
        "如果我想看电影，你帮我选一部。",
        "等我回家，你再帮我选一部。",
        "我给你选了一件。",
        "你已经帮我选好了。",
        "你给我选的这件很好看。",
        "你推荐过这本书。",
    ],
)
def test_reported_deferred_and_negated_choices_are_not_current_tasks(text: str) -> None:
    assert not is_choice_request(text)


def test_concentration_and_old_listening_do_not_hide_a_delegated_choice(tmp_path: Path) -> None:
    model = RecordingLLM()
    client = client_for(tmp_path, model)
    configure(client, emotional_intensity="intense")
    first = message(client, "先听我吐槽，不用给建议。")
    assert client.post("/api/chat", json=first).status_code == 200
    current = "给我选部悬疑片吧，别恐怖，我怕。"
    reply = client.post("/api/chat", json={**first, "request_id": "choose-now", "content": current})
    assert reply.status_code == 200, reply.text
    system = model.inputs[-1][0].content
    assert "[EMOTIONAL EXPRESSION]" in system
    assert "[CURRENT TASK]" in system
    assert model.inputs[-1][-1].content == current
    stored = client.app.state.host.memory.store.get_turn(
        reply.json()["assistant"]["id"], LOCAL_USER
    )
    assert stored.metadata["response_goal"] in {"direct_answer", "problem_solve"}
