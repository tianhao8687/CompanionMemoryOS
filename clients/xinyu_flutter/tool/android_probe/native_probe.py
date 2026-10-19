"""Runs inside the installed, unmodified APK's Python/JNI runtime; emulator only."""

import builtins
import json
import time
import traceback
from pathlib import Path

from java import jclass

from companion_agent.automation.hub import ToolHub, digest
from companion_agent.automation.models import AutomationConfig, MCPServerConfig
from companion_agent.automation.native_client import NativeClients
from companion_agent.integrations.droid_android import android_phone_client
from companion_agent.integrations.netease_android import android_client
from companion_memoryos.config import load_config
from companion_memoryos.database import Database

context = builtins._xinyu_smoke_context
phase = builtins._xinyu_smoke_phase
run_id = builtins._xinyu_smoke_run
phone, music = android_phone_client(context), android_client(context)
server = phone.template()
catalog = phone.discover(server)
definitions = {t["name"]: t for t in catalog}
checks = []
observations = {}


def check(name, fn):
    try:
        detail = fn()
        checks.append({"name": name, "status": "passed", "detail": detail})
    except Exception as error:
        checks.append(
            {
                "name": name,
                "status": "failed",
                "error": repr(error),
                "trace": traceback.format_exc(),
            }
        )


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def call(name, **args):
    return phone.call(server, name, args, definitions[name])["data"]


def successful(name, **args):
    data = call(name, **args)
    require(data["status"] == "succeeded", data)
    return data


def denied(name, **args):
    data = call(name, **args)
    require(data["status"] == "failed", data)
    return data


def catalog_check():
    require(len(catalog) == 30, f"Expected 30 tools, got {len(catalog)}")
    require(server.tools["query_screen"].mode == "off", "UI must default off")
    require(server.tools["set_volume"].mode == "ask", "Volume must require approval")
    return {"tools": len(catalog), "state": phone.state()}


def native_dependencies():
    import sqlite3

    import rpds
    import tiktoken
    from pydantic import TypeAdapter

    from companion_agent.nook_drawing import render_drawing

    require(TypeAdapter(list[int]).validate_python([1, 2]) == [1, 2], "Pydantic failed")
    require(rpds.HashTrieMap({"synthetic": 1})["synthetic"] == 1, "rpds failed")
    tokenizer = tiktoken.Encoding(
        name="synthetic",
        pat_str=".",
        mergeable_ranks={bytes([n]): n for n in range(256)},
        special_tokens={},
    )
    require(tokenizer.decode(tokenizer.encode("本机测试")) == "本机测试", "tiktoken failed")
    # Android intentionally builds Pillow without codecs. Exercise the actual
    # app's drawing/compositing/pixel path, rather than a PNG encoder it does not use.
    drawing = render_drawing(
        {
            "palette": ["#ffffff"],
            "outline": -1,
            "layers": [{"name": "synthetic", "ops": [["rect", 0, 8, 8, 23, 23]]}],
        }
    )
    require(
        len(drawing["rows"]) == 32
        and drawing["rows"][8][8] == "0"
        and drawing["rows"][0][0] == ".",
        "Pillow drawing/pixel readback failed",
    )
    with sqlite3.connect(":memory:") as database:
        database.execute("CREATE VIRTUAL TABLE synthetic USING fts5(content)")
        database.execute("INSERT INTO synthetic VALUES ('smoke')")
        require(
            database.execute(
                "SELECT count(*) FROM synthetic WHERE synthetic MATCH 'smoke'"
            ).fetchone()[0]
            == 1,
            "FTS5 failed",
        )
    return {"pydantic_core": True, "rpds": True, "tiktoken": True, "Pillow": True, "FTS5": True}


def approval():
    directory = Path(str(context.getFilesDir())) / "smoke" / run_id / phase
    database = Database(directory, load_config())
    clients = NativeClients({"droid": phone, "netease": music})
    hub = ToolHub(database, clients)
    hub.server_available = clients.accepts
    config = AutomationConfig(servers=[server.model_copy(update={"enabled": True})])
    hub.configure(config)
    hub.discover("droid")
    audio = context.getSystemService("audio")
    before = audio.getStreamVolume(3)
    level = 2 if before != 2 else 3
    name = "mcp_droid_" + digest("set_volume")[:12]
    try:
        pending = hub.invoke(name, {"level": level}, "synthetic", "approval")
        require(pending["status"] == "pending", pending)
        require(audio.getStreamVolume(3) == before, "Pending action changed volume")
        approved = hub.approve(pending["action_id"], True)
        require(approved["status"] == "succeeded", approved)
        require(audio.getStreamVolume(3) == level, "OS did not apply volume")
        repeated = hub.invoke(name, {"level": level}, "synthetic", "approval")
        require(repeated.get("reused") is True, "Retry was not deduplicated")
        pending = hub.invoke(name, {"level": before}, "synthetic", "revocation")
        config.servers[0].enabled = False
        hub.configure(config)
        try:
            hub.approve(pending["action_id"], True)
        except ValueError:
            pass
        else:
            raise AssertionError("Disabled connection still approved pending action")
        require(audio.getStreamVolume(3) == level, "Revoked action changed volume")
        return {
            "before": before,
            "applied": level,
            "approval": True,
            "dedup": True,
            "revocation": True,
        }
    finally:
        audio.setStreamVolume(3, before, 0)


def music_check():
    music_server = MCPServerConfig(id="netease", label="Music", transport="native", enabled=True)
    definitions = {t["name"]: t for t in music.discover(music_server)}
    require(len(definitions) == 10, "Expected 10 music tools")
    require(
        "lyrics"
        in definitions["netease_search_songs"]["inputSchema"]["properties"]["search_type"]["enum"],
        "Missing lyric search",
    )
    status = music.call(music_server, "netease_status", {}, definitions["netease_status"])["data"]
    require(status["installed"] is False, "Expected a clean emulator without NetEase")
    control = music.call(
        music_server, "netease_control", {"action": "pause"}, definitions["netease_control"]
    )["data"]
    require(control["status"] == "failed", "Missing player should fail clearly")
    return {"tools": len(definitions), "status": status, "missing_player_control": control}


def brightness():
    settings = jclass("android.provider.Settings$System")
    resolver = context.getContentResolver()
    before = settings.getInt(resolver, "screen_brightness", 128)
    mode = settings.getInt(resolver, "screen_brightness_mode", 0)
    try:
        data = successful("set_brightness", level=123)
        require(
            settings.getInt(resolver, "screen_brightness") == 123, "Brightness readback mismatch"
        )
        return data
    finally:
        settings.putInt(resolver, "screen_brightness", before)
        settings.putInt(resolver, "screen_brightness_mode", mode)


def ui_controls():
    target = "com.xinyu.smoke"
    deadline = time.monotonic() + 10
    while not phone.state()["permissions"]["accessibility"] and time.monotonic() < deadline:
        time.sleep(0.2)
    screen = successful("query_screen", expected_package=target)
    require(screen["package_name"] == target, screen)
    require("synthetic-secret-0227" not in json.dumps(screen), "Password content leaked")
    require(any(n.get("is_password") for n in screen["nodes"]), "Password node not inspected")
    successful("click_node", expected_package=target, text="Tap target")
    time.sleep(0.3)
    changed = successful("find_node", expected_package=target, text="Tapped successfully")
    require(changed["count"] == 1, changed)
    successful(
        "set_node_text", expected_package=target, match_text="Input target", text="Synthetic input"
    )
    time.sleep(0.3)
    typed = successful("find_node", expected_package=target, text="Synthetic input")
    require(typed["count"] == 1, typed)
    return {
        "package": target,
        "click_readback": True,
        "input_readback": True,
        "password_masked": True,
    }


def gestures():
    target = "com.xinyu.smoke"
    successful("long_click_node", expected_package=target, text="Long press target")
    time.sleep(0.3)
    held = successful("find_node", expected_package=target, text="Long press verified")
    require(held["count"] == 1, held)
    before = successful("query_screen", expected_package=target, max_nodes=40)
    containers = successful(
        "find_node", expected_package=target, class_name="android.widget.ScrollView"
    )
    container = containers["nodes"][0]
    # Bounds come from the actual app tree, never a guessed screen coordinate.
    bounds = container["bounds"]
    if isinstance(bounds, dict):
        left, top, right, bottom = (bounds[k] for k in ("left", "top", "right", "bottom"))
    else:
        import re

        left, top, right, bottom = map(int, re.findall(r"\d+", str(bounds)))
    x = (left + right) // 2
    successful(
        "gesture",
        expected_package=target,
        points=[[x, bottom - 80], [x, top + 80]],
        duration_ms=400,
    )
    time.sleep(0.4)
    after = successful("query_screen", expected_package=target, max_nodes=40)
    require(before["nodes"] != after["nodes"], "Swipe did not change the visible list")
    denied("gesture", expected_package=target, points=[[0, 0], [1, 1]])
    denied("long_click_node", expected_package="synthetic.missing", text="Long press verified")
    return {"long_press_readback": True, "swipe_readback": True, "bounds_checked": True}


def phone_companion_chat():
    from companion_agent.app import ChatInput, create_app
    from companion_agent.automation.loop import ModelStep, ToolCall
    from companion_agent.automation.models import PhoneComfortConfig, ToolRule
    from companion_agent.offline import OfflineModel
    from companion_agent.romance import SettingsUpdate

    class DecisionModel(OfflineModel):
        def __init__(self):
            self.plan = []

        def generate_step(self, messages, tools, timeout):
            if self.plan:
                name, arguments = self.plan.pop(0)
                tool_call = ToolCall(
                    id="synthetic-phone", name=name, arguments=json.dumps(arguments)
                )
                return ModelStep(
                    model="synthetic",
                    total_tokens=100,
                    calls=[tool_call],
                    message={
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [
                            {
                                "id": tool_call.id,
                                "type": "function",
                                "function": {"name": name, "arguments": tool_call.arguments},
                            }
                        ],
                    },
                )
            return ModelStep(
                model="synthetic",
                text="先歇一会儿。",
                total_tokens=20,
                message={"role": "assistant", "content": "先歇一会儿。"},
            )

    directory = Path(str(context.getFilesDir())) / "smoke" / run_id / ("phone-companion-" + phase)
    require(not directory.exists(), "Phone companion probe needs fresh synthetic storage")
    model = DecisionModel()
    host = create_app(
        directory, llm=model, background_services=False, interactive_tools=True, native_phone=phone
    ).state.host
    host.save_settings(
        SettingsUpdate(
            settings=host.settings.model_copy(
                update={
                    "storage_consent": True,
                    "model_consent": True,
                }
            )
        )
    )
    conversation = host.conversations()[0]["id"]
    selected = server.model_copy(deep=True)
    selected.enabled = True
    for name in ["get_settings", "set_brightness", "get_light_level", "get_proximity"]:
        selected.tools[name] = ToolRule(mode="allow")
    host.tools.configure(
        AutomationConfig(
            servers=[selected],
            phone_comfort=PhoneComfortConfig(
                enabled=True,
                media=False,
                screen=True,
            ),
        )
    )
    host.tools.discover("droid")
    original = successful("get_settings")
    try:
        successful("set_brightness", level=180, automatic=phase == "environment_auto")
        before = successful("get_settings")
        require(before["screen_brightness"] > 64, before)
        model.plan = [
            (
                "app_comfort_phone",
                {"scene": "rest", "evidence": "屏幕晃得我难受", "adjustments": ["screen"]},
            )
        ]
        host.chat(
            ChatInput(
                conversation_id=conversation,
                request_id="companion-first",
                content="我眼睛好酸，屏幕晃得我难受",
            )
        )
        after = successful("get_settings")
        receipt = next(
            a for a in host.tools.store.actions() if a["tool_name"] == "app_comfort_phone"
        )
        # Keep actual native results even when a subsequent assertion fails.
        observations[phase] = {
            "actions": host.tools.store.actions(),
            "before": before,
            "after": after,
        }
        if phase != "environment_dim":
            expected_reason = {
                "environment_bright": "environment_bright",
                "environment_covered": "possibly_covered",
                "environment_auto": "automatic_brightness",
                "environment_background": "unavailable",
            }[phase]
            require(receipt["result"]["environment"]["reason"] == expected_reason, receipt)
            require(not receipt["result"]["verified"], receipt)
            require(not host.phone_comfort.active(), "Unexpected saved adjustment")
            require(after["brightness_mode"] == before["brightness_mode"], after)
            if phase != "environment_auto":
                require(after["screen_brightness"] == before["screen_brightness"], after)
            require(
                not any(
                    a["tool_name"] == "mcp_droid_" + digest("set_brightness")[:12]
                    for a in host.tools.store.actions()
                ),
                "Unexpected native brightness write",
            )
            return {
                "scope": "installed_apk_chat_real_sensors_scripted_model",
                "before": before,
                "after": after,
                "decision": receipt["result"],
            }
        require(after["screen_brightness"] == before["screen_brightness"] - 40, after)
        require(after["brightness_mode"] == 0, after)
        require(receipt["result"]["verified"], receipt)
        require(abs(receipt["result"]["environment"]["lux"] - 8) < 1, receipt)
        with host.phone_comfort.from_button():
            restored = host.tools.invoke("app_restore_phone", {}, conversation, "companion-restore")
        require(restored["verified"], restored)
        require(
            successful("get_settings")["screen_brightness"] == before["screen_brightness"],
            "Brightness not restored",
        )
        model.plan = [
            (
                "app_comfort_phone",
                {"scene": "rest", "evidence": "我还是好累啊", "adjustments": ["screen"]},
            )
        ]
        host.chat(
            ChatInput(
                conversation_id=conversation,
                request_id="companion-cooldown",
                content="我还是好累啊",
            )
        )
        require(not host.phone_comfort.active(), "Cooldown applied a second adjustment")
        model.plan = []
        host.chat(
            ChatInput(
                conversation_id=conversation, request_id="companion-stop", content="别替我调整了"
            )
        )
        require(not host.tools.config.phone_comfort.enabled, "Opt-out was not saved")
        return {
            "scope": "installed_apk_chat_with_scripted_model_and_real_android_bridge",
            "model_calls": 0,
            "brightness_adjusted": True,
            "manual_brightness_restored": True,
            "environment": receipt["result"]["environment"],
            "cooldown": True,
            "optout": True,
        }
    finally:
        successful(
            "set_brightness",
            level=max(10, original["screen_brightness"]),
            automatic=original["brightness_mode"] == 1,
        )


check("catalog_and_defaults", catalog_check)
if phase == "base":
    check("android_native_dependencies", native_dependencies)
    for name in (
        "get_device_info",
        "get_battery_info",
        "get_connectivity",
        "get_screen_state",
        "get_settings",
        "get_next_alarm",
        "get_dnd_status",
        "list_installed_apps",
    ):
        check(name, lambda name=name: successful(name))
    check("real_volume_approval_dedup_revocation", approval)
    check("music_catalog_and_missing_player", music_check)
if phase in {"base", "revoked"}:
    check("brightness_permission_denied", lambda: denied("set_brightness", level=123))
    check("dnd_permission_denied", lambda: denied("set_dnd_mode", mode="priority"))
    check(
        "accessibility_permission_denied",
        lambda: denied("query_screen", expected_package="com.xinyu.smoke"),
    )
if phase == "granted":
    check("real_accessibility_read_click_input", ui_controls)
    check("real_long_press_and_swipe", gestures)
    check("brightness_os_readback", brightness)
    check(
        "self_ui_blocked", lambda: denied("query_screen", expected_package=context.getPackageName())
    )
    check(
        "settings_ui_blocked",
        lambda: denied("query_screen", expected_package="com.android.settings"),
    )
    check(
        "wrong_foreground_blocked",
        lambda: denied("query_screen", expected_package="synthetic.missing"),
    )
    check("dnd_os_readback", lambda: successful("set_dnd_mode", mode="priority"))
    check("dnd_restore", lambda: successful("set_dnd_mode", mode="off"))
if phase.startswith("environment_"):
    check("real_chat_phone_companion_" + phase, phone_companion_chat)
builtins._xinyu_smoke_result = json.dumps(
    {"phase": phase, "checks": checks, "observations": observations}, ensure_ascii=False
)
