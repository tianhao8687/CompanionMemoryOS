from __future__ import annotations

import base64
from typing import Any
from xml.sax.saxutils import escape

import pytest

from companion_agent.integrations.phone import WECHAT, PhoneBridge, build_server


class SimulatedPhone(PhoneBridge):
    def __init__(self) -> None:
        super().__init__("test-device", [WECHAT], ["小雨"])
        self.draft = ""
        self.title = "小雨"
        self.visible = "你好"
        self.ime = "com.android.adbkeyboard/.AdbIME"
        self.commands: list[tuple[str, ...]] = []

    def command(self, *args: str) -> str:
        self.commands.append(args)
        if args == ("get-state",):
            return "device"
        if args[:3] == ("shell", "dumpsys", "window"):
            return f"mCurrentFocus=Window{{abc u0 {WECHAT}/.ui.LauncherUI}}"
        if args[:2] == ("exec-out", "uiautomator"):
            nodes = [
                ("", "android.widget.FrameLayout", "[0,0][600,1000]", "false"),
                (self.title, "android.widget.TextView", "[180,40][350,90]", "false"),
                (self.visible, "android.widget.TextView", "[50,200][450,250]", "false"),
                (self.draft, "android.widget.EditText", "[50,800][450,850]", "true"),
                ("发送", "android.widget.Button", "[460,800][560,850]", "true"),
                ("返回", "android.widget.Button", "[0,40][80,90]", "true"),
            ]
            content = "".join(
                f'<node package="{WECHAT}" text="{escape(text)}" class="{kind}" '
                f'bounds="{bounds}" clickable="{clickable}" enabled="true"/>'
                for text, kind, bounds, clickable in nodes
            )
            return '<?xml version="1.0" encoding="utf-8"?><hierarchy>' + content + "</hierarchy>"
        if args[:3] == ("shell", "settings", "get"):
            return self.ime
        if "ADB_INPUT_B64" in args:
            self.draft = base64.b64decode(args[-1]).decode()
        if args == ("shell", "input", "tap", "510", "825"):
            self.visible, self.draft = self.draft, ""
        return ""


def test_phone_scope_stale_screen_and_sensitive_controls() -> None:
    bridge = SimulatedPhone()
    screen = bridge.screen()
    assert bridge.status()["connection"] == "device"
    with pytest.raises(ValueError, match="白名单"):
        bridge.open_app("com.android.settings")
    with pytest.raises(ValueError, match="变化"):
        bridge.tap(5, "old-screen")
    with pytest.raises(ValueError, match="通用点击"):
        bridge.tap(4, screen["screen_id"])
    with pytest.raises(ValueError, match="通用点击"):
        bridge.tap(3, screen["screen_id"])
    bridge.visible = "确认付款"
    with pytest.raises(ValueError, match="敏感"):
        bridge.tap(5, bridge.screen()["screen_id"])
    assert not any(command[:3] == ("shell", "input", "tap") for command in bridge.commands)


def test_wechat_recipient_input_method_and_existing_draft() -> None:
    bridge = SimulatedPhone()
    with pytest.raises(ValueError, match="白名单"):
        bridge.current_chat("其他人")
    bridge.title = "其他人"
    with pytest.raises(ValueError, match="无法确认"):
        bridge.current_chat("小雨")
    bridge.title = "小雨"
    bridge.draft = "用户未发的草稿"
    with pytest.raises(ValueError, match="草稿"):
        bridge.send_message("小雨", "晚安", bridge.screen()["screen_id"])
    bridge.draft = ""
    bridge.ime = "another.keyboard/.InputMethod"
    with pytest.raises(ValueError, match="手动选用"):
        bridge.send_message("小雨", "晚安", bridge.screen()["screen_id"])


def test_wechat_chinese_roundtrip_and_exact_draft_verification() -> None:
    bridge = SimulatedPhone()
    result = bridge.send_message("小雨", "晚安，明天见", bridge.screen()["screen_id"])
    assert result["status"] == "succeeded"
    assert bridge.visible == "晚安，明天见" and bridge.draft == ""
    assert any("ADB_INPUT_B64" in command for command in bridge.commands)
    assert not any("ime" in command for command in bridge.commands)


def test_wechat_unverified_send_is_uncertain(monkeypatch: pytest.MonkeyPatch) -> None:
    bridge = SimulatedPhone()
    before = bridge.current_chat
    calls = 0

    def changing(contact: str, screen: dict[str, Any] | None = None) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("screen changed after send")
        return before(contact, screen)

    monkeypatch.setattr(bridge, "current_chat", changing)
    assert (
        bridge.send_message("小雨", "hello", bridge.screen()["screen_id"])["status"] == "uncertain"
    )


def test_phone_mcp_exposes_only_scoped_actions() -> None:
    import asyncio

    server = build_server(SimulatedPhone())
    tools = asyncio.run(server.list_tools())
    assert {t.name for t in tools} == {
        "phone_status",
        "phone_read_screen",
        "phone_open_app",
        "phone_tap",
        "phone_navigate",
        "wechat_read_current_chat",
        "wechat_send_message",
    }
