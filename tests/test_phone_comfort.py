"""Actual chat/ToolHub/storage flow with a synthetic Android bridge; no live model/device."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from companion_agent.app import create_app
from companion_agent.automation.models import AutomationConfig, PhoneComfortConfig, ToolRule
from companion_agent.integrations.droid_android import AndroidPhoneClient
from companion_agent.phone_comfort import RESTORE, TOOL, evidence_in_turn, refused
from tests.test_app_assistant import setup_host
from tests.test_droid_android import tool
from tests.test_music_requests import SongModel
from tests.test_romance_app import HEADERS


class Phone:
    def __init__(self) -> None:
        self.settings = {
            "volume_media": 8,
            "volume_media_max": 15,
            "music_active": True,
            "audio_mode": 0,
            "screen_brightness": 160,
            "brightness_mode": 0,
        }
        self.dnd = "all"
        self.writes: list[tuple[str, dict[str, Any]]] = []
        self.write_result = "succeeded"
        self.race = False
        self.reads: list[str] = []
        self.light = {
            "status": "succeeded",
            "foreground": True,
            "age_ms": 10,
            "lux": 8,
            "readings": [{"lux": 8}],
        }
        self.proximity = {"status": "succeeded", "foreground": True, "age_ms": 5, "is_near": False}
        self.catalog = [
            tool("get_light_level", {"duration_ms": {"type": "integer"}}, []),
            tool("get_proximity", {}, []),
            tool("get_settings", {}, []),
            tool("get_dnd_status", {}, []),
            tool(
                "set_volume",
                {
                    "level": {"type": "integer", "minimum": 0},
                    "stream": {"type": "string", "enum": ["media"]},
                },
                ["level"],
            ),
            tool(
                "set_brightness",
                {"level": {"type": "integer", "minimum": 0, "maximum": 255}},
                ["level"],
            ),
            tool(
                "set_dnd_mode",
                {"mode": {"type": "string", "enum": ["off", "priority", "alarms", "none"]}},
                ["mode"],
            ),
        ]

    def __call__(self, operation: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        if operation == "state":
            return {"supported": True}
        if operation == "catalog":
            return {"supported": True, "tools": copy.deepcopy(self.catalog)}
        name, args = payload["name"], payload["arguments"]
        self.reads.append(name)
        if name == "get_light_level":
            return copy.deepcopy(self.light)
        if name == "get_proximity":
            return copy.deepcopy(self.proximity)
        if name == "get_settings":
            return {"status": "succeeded", **self.settings}
        if name == "get_dnd_status":
            return {"status": "succeeded", "filter": self.dnd, "has_policy_access": True}
        if self.race:
            self.settings["volume_media"] = 12
            return {"status": "failed"}
        if args.get("require_idle_audio") and self.settings["audio_mode"] != 0:
            return {"status": "failed"}
        self.writes.append((name, args))
        if self.write_result != "succeeded":
            return {"status": self.write_result}
        if name == "set_volume":
            self.settings["volume_media"] = args["level"]
        elif name == "set_brightness":
            self.settings["screen_brightness"] = args["level"]
            self.settings["brightness_mode"] = int(args["automatic"])
        else:
            self.dnd = "all" if args["mode"] == "off" else args["mode"]
        return {"status": "succeeded"}


@pytest.fixture
def companion(tmp_path: Path):
    phone, model = Phone(), SongModel()
    app = create_app(
        tmp_path,
        llm=model,
        background_services=False,
        interactive_tools=True,
        native_phone=AndroidPhoneClient(phone),
    )
    host = app.state.host
    with TestClient(app, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        conversation = setup_host(host)
        template = AndroidPhoneClient(phone).template()
        template.enabled = True
        template.tools = {t["name"]: ToolRule(mode="allow") for t in phone.catalog}
        host.tools.configure(
            AutomationConfig(
                servers=[template],
                phone_comfort=PhoneComfortConfig(
                    enabled=True,
                    media=True,
                    screen=True,
                    interruptions=True,
                ),
            )
        )
        host.tools.discover("droid")
        yield client, host, phone, model, conversation


def chat(fixture: Any, text: str, plan: list[tuple[str, dict[str, Any]]], key: str = "comfort"):
    client, _, _, model, conversation = fixture
    model.plan = plan
    result = client.post(
        "/api/chat", json={"conversation_id": conversation, "request_id": key, "content": text}
    )
    assert result.status_code == 200, result.text
    return result.json()


def adjust(text: str, channels: list[str] | None = None):
    return [(TOOL, {"scene": "rest", "evidence": text, "adjustments": channels or ["screen"]})]


def receipt(host: Any, name: str = TOOL):
    return next(a["result"] for a in host.tools.store.actions() if a["tool_name"] == name)


def test_chat_without_command_uses_environment_then_restores_manual_brightness(companion):
    _, host, phone, model, _ = companion
    text = "我眼睛好酸，屏幕晃得我难受"
    chat(companion, text, adjust("屏幕晃得我难受", ["screen", "media"]))
    assert phone.settings["screen_brightness"] == 120
    assert phone.settings["brightness_mode"] == 0
    assert phone.settings["volume_media"] == 6
    assert receipt(host)["verified"]
    assert "结合当前聊天语义判断" in json.dumps(model.histories, ensure_ascii=False)
    assert all(args["require_idle_audio"] for _, args in phone.writes)
    chat(companion, "我缓过来了", [(RESTORE, {"evidence": "我缓过来了"})], "restored")
    assert phone.settings["screen_brightness"] == 160
    assert phone.settings["brightness_mode"] == 0
    assert phone.settings["volume_media"] == 8
    assert not host.phone_comfort.active()
    chat(companion, text, adjust("屏幕晃得我难受"), "after-restore")
    assert receipt(host)["reason"] == "cooldown"
    assert len(phone.writes) == 4


def test_model_can_choose_only_conversation(companion):
    chat(companion, "今天有些难过，想跟你说说", [])
    assert not companion[2].writes and not companion[1].phone_comfort.active()


@pytest.mark.parametrize(
    "text,evidence",
    [
        ("“我好累”是电影台词", "我好累"),
        ("如果我好累你会怎么办", "我好累"),
        ("我朋友好累", "朋友好累"),
        ("昨天我好累", "我好累"),
        ("给我写个我好累的功能", "我好累"),
        ("我很开心", "我好累"),
        ("我好累，帮我修改报告", "我好累"),
    ],
)
def test_quotes_history_tasks_and_fabricated_evidence_cannot_adjust(companion, text, evidence):
    chat(companion, text, adjust(evidence))
    assert not companion[2].writes


def test_paused_or_quiet_device_is_not_turned_up(companion):
    companion[2].settings.update(volume_media=0, screen_brightness=40)
    chat(companion, "我好累啊", adjust("我好累啊", ["media", "screen"]))
    assert not companion[2].writes
    assert receipt(companion[1])["environment"]["reason"] == "already_dim"


@pytest.mark.parametrize("mode", ["ask", "off"])
def test_permissions_never_prompt_or_expand_automatically(companion, mode):
    _, host, phone, _, _ = companion
    host.tools.config.servers[0].tools["set_brightness"].mode = mode
    chat(companion, "我好累啊", adjust("我好累啊"))
    assert not phone.writes
    assert not any(a["status"] == "pending" for a in host.tools.store.actions())


def test_one_action_per_cooldown_across_chats_and_retry(companion):
    text = "我好累啊"
    chat(companion, text, adjust(text))
    chat(companion, text, adjust(text))
    chat(companion, text, adjust(text), "second")
    assert len(companion[2].writes) == 1


def test_stop_is_saved_without_requiring_a_model_tool(companion):
    _, host, phone, _, _ = companion
    chat(companion, "别替我调整了", [])
    assert not host.tools.config.phone_comfort.enabled
    with host.database.connection() as db:
        saved = json.loads(db.execute("SELECT data FROM agent_config").fetchone()[0])
    assert saved["config"]["phone_comfort"]["enabled"] is False
    chat(companion, "我好累啊", adjust("我好累啊"), "after-stop")
    assert not phone.writes


def test_restore_button_preserves_manual_changes_and_works_when_disabled(companion):
    client, host, phone, _, _ = companion
    chat(companion, "我好累啊", adjust("我好累啊", ["screen", "media"]))
    phone.settings["screen_brightness"] = 200
    host.tools.config.phone_comfort.enabled = False
    result = client.post("/api/automation/phone-comfort/restore")
    assert result.status_code == 200 and result.json()["verified"]
    assert phone.settings["screen_brightness"] == 200
    assert phone.settings["volume_media"] == 8
    assert not host.phone_comfort.active()


def test_uncertain_action_is_not_claimed_or_repeated(companion):
    _, host, phone, _, _ = companion
    phone.write_result = "uncertain"
    chat(companion, "我好累啊", adjust("我好累啊"))
    assert not receipt(host)["verified"]
    chat(companion, "我还是很累", adjust("我还是很累"), "second")
    assert len(phone.writes) == 1


def test_in_call_does_not_change_settings(companion):
    companion[2].settings["audio_mode"] = 2
    chat(companion, "我好累啊", adjust("我好累啊", ["screen", "media"]))
    assert not companion[2].writes


def test_dnd_only_uses_priority_and_does_not_override_existing_dnd(companion):
    _, host, phone, _, _ = companion
    chat(companion, "通知一直响得我好烦", adjust("通知一直响得我好烦", ["interruptions"]))
    assert phone.dnd == "priority" and receipt(host)["verified"]
    phone.dnd = "alarms"
    companion[0].post("/api/automation/phone-comfort/restore")
    assert phone.dnd == "alarms" and len(phone.writes) == 1


def test_restart_preserves_restore_state(companion, tmp_path):
    _, _, phone, _, _ = companion
    chat(companion, "我好累啊", adjust("我好累啊"))
    restarted = create_app(
        tmp_path,
        background_services=False,
        interactive_tools=True,
        native_phone=AndroidPhoneClient(phone),
    )
    with TestClient(restarted, base_url="http://127.0.0.1", headers=HEADERS) as client:
        client.get("/")
        state = client.get("/api/automation").json()
        assert state["phone_comfort"]["active"][0]["channel"] == "screen"
        assert client.post("/api/automation/phone-comfort/restore").json()["verified"]
        assert phone.settings["brightness_mode"] == 0


def test_upgrade_refreshes_phone_schemas_without_enabling_new_permissions(companion, tmp_path):
    _, host, phone, _, _ = companion
    host.tools.config.servers[0].tools["set_volume"].mode = "ask"
    for item in host.tools.catalog["droid"]:
        item["inputSchema"]["properties"].pop("expected_level", None)
    host.tools.persist()
    restarted = create_app(
        tmp_path,
        background_services=False,
        interactive_tools=True,
        native_phone=AndroidPhoneClient(phone),
    ).state.host
    brightness = next(t for t in restarted.tools.catalog["droid"] if t["name"] == "set_brightness")
    assert "expected_level" in brightness["inputSchema"]["properties"]
    assert restarted.tools.config.servers[0].tools["set_volume"].mode == "ask"
    assert not phone.writes


def test_evidence_and_optout_scope():
    assert evidence_in_turn("今天我好累，屏幕晃得难受", "屏幕晃得难受")
    assert refused("别替我调整了")
    assert not refused("她说“别替我调整了”")
    assert not refused("如果我说别替我调整了，你会怎么办")
    assert not AutomationConfig().phone_comfort.enabled


@pytest.mark.parametrize(
    "case,reason",
    [
        ("bright", "environment_bright"),
        ("covered", "possibly_covered"),
        ("changing", "changing_light"),
        ("missing", "unavailable"),
        ("stale", "unavailable"),
        ("background", "unavailable"),
        ("nan", "unavailable"),
        ("empty", "unavailable"),
        ("sensor_permission", "unavailable"),
        ("unknown_proximity", "possibly_covered"),
    ],
)
def test_unreliable_or_bright_environment_keeps_screen(companion, case, reason):
    _, host, phone, _, _ = companion
    if case == "bright":
        phone.light["readings"] = [{"lux": 20000}]
    elif case == "covered":
        phone.proximity["is_near"] = True
    elif case == "changing":
        phone.light["readings"] = [{"lux": 1}, {"lux": 45}]
    elif case == "missing":
        phone.light = {"status": "failed"}
    elif case == "stale":
        phone.light["age_ms"] = 6001
    elif case == "background":
        phone.proximity["foreground"] = False
    elif case == "nan":
        phone.light["readings"] = [{"lux": -1}]
    elif case == "empty":
        phone.light["readings"] = []
    elif case == "sensor_permission":
        host.tools.config.servers[0].tools["get_light_level"].mode = "ask"
    else:
        phone.proximity.pop("is_near")
    chat(companion, "我眼睛好累啊", adjust("我眼睛好累啊"))
    assert not phone.writes and not host.phone_comfort.active()
    assert receipt(host)["environment"]["reason"] == reason
    assert not any(a["status"] == "pending" for a in host.tools.store.actions())


def test_automatic_brightness_stays_enabled_and_needs_no_sensor_read(companion):
    _, host, phone, _, _ = companion
    phone.settings["brightness_mode"] = 1
    chat(companion, "我眼睛好累啊", adjust("我眼睛好累啊"))
    assert phone.settings["brightness_mode"] == 1 and not phone.writes
    assert "get_light_level" not in phone.reads
    assert receipt(host)["environment"]["reason"] == "automatic_brightness"


def test_twilight_uses_smaller_step_and_missing_light_does_not_block_media(companion):
    _, host, phone, _, _ = companion
    phone.light["readings"] = [{"lux": 35}, {"lux": 36}]
    chat(companion, "我好累啊", adjust("我好累啊", ["screen", "media"]))
    assert phone.settings["screen_brightness"] == 140
    assert phone.settings["volume_media"] == 6
    assert receipt(host)["environment"]["eligible"]
    assert phone.writes[0][1]["require_foreground"] is True


def test_sensor_unavailable_still_allows_selected_media(companion):
    phone = companion[2]
    phone.light = {"status": "failed"}
    chat(companion, "声音好吵我眼睛也好累", adjust("声音好吵我眼睛也好累", ["screen", "media"]))
    assert phone.settings["screen_brightness"] == 160
    assert phone.settings["volume_media"] == 6
    assert len(phone.writes) == 1


def test_restores_legacy_automatic_mode_without_sensor_access(companion):
    client, host, phone, _, _ = companion
    chat(companion, "我好累啊", adjust("我好累啊"))
    with host.database.connection() as db:
        row = db.execute(
            "SELECT before_state FROM phone_comfort_changes WHERE channel='screen'"
        ).fetchone()
        before = json.loads(row["before_state"])
        before["automatic"] = True  # A pending adjustment saved by 0.2.29.
        db.execute(
            "UPDATE phone_comfort_changes SET before_state=? WHERE channel='screen'",
            (json.dumps(before),),
        )
    host.tools.config.servers[0].tools["get_light_level"].mode = "off"
    assert client.post("/api/automation/phone-comfort/restore").json()["verified"]
    assert phone.settings["brightness_mode"] == 1
