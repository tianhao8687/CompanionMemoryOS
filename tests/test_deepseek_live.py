"""Explicit opt-in paid smoke test; never require a network/credential in normal CI."""

from __future__ import annotations

import os

import pytest

from companion_agent.context import ChatMessage
from companion_agent.deepseek import DeepSeekConfig, DeepSeekLLM


@pytest.mark.skipif(
    os.environ.get("RUN_DEEPSEEK_LIVE") != "1" or not os.environ.get("DEEPSEEK_API_KEY"),
    reason="real DeepSeek test requires RUN_DEEPSEEK_LIVE=1 and DEEPSEEK_API_KEY",
)
def test_real_deepseek_text_completion() -> None:
    model = DeepSeekLLM(
        DeepSeekConfig(
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-flash"),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        )
    )
    response = model.generate(
        [
            ChatMessage(role="system", content="你是一位坦诚温柔的 AI 伴侣，请用一句中文回应。"),
            ChatMessage(role="user", content="今天有点累，想和你聊一会儿。"),
        ]
    )
    assert response.text.strip()
    assert response.usage is not None
