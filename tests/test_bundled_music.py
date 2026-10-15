from pathlib import Path
from types import SimpleNamespace

import pytest

from companion_agent.automation import hub as hub_module
from companion_agent.automation.bundled_music import relocate_packaged_music
from companion_agent.automation.hub import ToolHub
from companion_agent.automation.models import AutomationConfig, MCPServerConfig
from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from tests.test_agent_automation import FakeMCP

OLD = r"C:\old\engine\xinyu-engine.exe"
NEW = r"C:\new\engine\xinyu-engine.exe"


def config(**changes):
    return AutomationConfig(
        servers=[
            MCPServerConfig.model_validate(
                {
                    "id": "netease",
                    "label": "网易云",
                    "enabled": True,
                    "command": OLD,
                    "args": ["--mcp-server", "netease"],
                    "tools": {"echo_contact": {"mode": "ask", "arguments": {"contact": ["小雨"]}}},
                    **changes,
                }
            )
        ]
    )


def test_upgrade_persists_current_engine_preserves_rules_and_invalidates_pending_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database(tmp_path, load_config())
    db.initialize()
    client = FakeMCP()
    old = ToolHub(db, client)
    old.configure(config())
    old.discover("netease")
    name = next(iter(old.bindings()))
    pending = old.invoke(name, {"contact": "小雨", "text": "合成测试"}, "conversation", "before")
    monkeypatch.setattr(
        hub_module, "sys", SimpleNamespace(platform="win32", frozen=True, executable=NEW)
    )
    current = ToolHub(db, client)
    assert current.config.servers[0].command == NEW
    assert current.config.servers[0].tools == old.config.servers[0].tools
    assert current.catalog == old.catalog
    with pytest.raises(ValueError):
        current.approve(pending["action_id"], True)
    assert not client.calls
    assert ToolHub(db, client).config.servers[0].command == NEW


@pytest.mark.parametrize(
    "changes",
    [
        {"id": "custom"},
        {"command": r"C:\custom\python.exe"},
        {"command": "xinyu-engine.exe"},
        {"args": ["--mcp-server", "other"]},
        {"env": {"CUSTOM": "CUSTOM_ENV"}},
    ],
)
def test_custom_commands_are_not_relocated(changes) -> None:
    value = config(**changes)
    before = value.model_dump()
    assert not relocate_packaged_music(value, NEW)
    assert value.model_dump() == before
