"""A small Android / visible-personal-WeChat MCP bridge. No arbitrary shell tool."""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

WECHAT = "com.tencent.mm"
SENSITIVE = (
    "支付",
    "转账",
    "红包",
    "收付款",
    "银行卡",
    "密码",
    "验证码",
    "注销",
    "删除",
    "付款",
    "授权登录",
    "payment",
    "password",
    "transfer",
    "delete account",
)


class PhoneBridge:
    def __init__(
        self, serial: str, packages: list[str], contacts: list[str], adb: str = "adb"
    ) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", serial):
            raise ValueError("设备序列号格式不正确。")
        if not packages or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.]+", p) for p in packages):
            raise ValueError("请填写允许操作的 Android 包名。")
        self.serial = serial
        self.packages = set(packages)
        self.contacts = set(contacts)
        self.adb = adb

    def command(self, *args: str) -> str:
        try:
            result = subprocess.run(
                [self.adb, "-s", self.serial, *args],
                capture_output=True,
                timeout=10,
                check=True,
                encoding="utf-8",
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError):
            raise ValueError("ADB 操作失败，请检查 USB、设备授权和 adb 路径。") from None
        if len(result.stdout) > 2_000_000:
            raise ValueError("设备返回内容过长。")
        return result.stdout

    def status(self) -> dict[str, Any]:
        state = self.command("get-state").strip()
        return {
            "status": "succeeded",
            "device": self.serial,
            "connection": state,
            "allowed_packages": sorted(self.packages),
            "allowed_contacts": sorted(self.contacts),
        }

    def screen(self) -> dict[str, Any]:
        foreground = self.command("shell", "dumpsys", "window", "windows")
        focus = re.search(r"mCurrentFocus=.*?\s([A-Za-z0-9_.]+)/", foreground)
        if not focus or focus.group(1) not in self.packages:
            raise ValueError("前台应用不在白名单，或手机处于锁屏状态。")
        raw = self.command("exec-out", "uiautomator", "dump", "/dev/tty")
        start, end = raw.find("<?xml"), raw.rfind("</hierarchy>")
        if start < 0 or end < 0:
            raise ValueError("无法读取界面，请解锁手机并打开支持无障碍树的界面。")
        xml = raw[start : end + len("</hierarchy>")]
        if "<!DOCTYPE" in xml or "<!ENTITY" in xml:
            raise ValueError("invalid device XML")
        root = ET.fromstring(xml)
        nodes: list[dict[str, Any]] = []
        for index, node in enumerate(root.iter("node")):
            if node.get("package") != focus.group(1):
                continue
            bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
            if not bounds:
                continue
            private = node.get("password") == "true"
            nodes.append(
                {
                    "id": index,
                    "text": "[私密输入]" if private else node.get("text", "")[:1000],
                    "description": "" if private else node.get("content-desc", "")[:300],
                    "class": node.get("class", ""),
                    "bounds": [int(v) for v in bounds.groups()],
                    "clickable": node.get("clickable") == "true" and not private,
                    "enabled": node.get("enabled") == "true",
                    "private": private,
                }
            )
        if len(nodes) > 500:
            raise ValueError("当前界面太复杂，请进入目标应用的具体页面。")
        return {
            "status": "succeeded",
            "package": focus.group(1),
            "screen_id": hashlib.sha256(xml.encode()).hexdigest()[:24],
            "nodes": nodes,
        }

    def checked(self, expected_screen: str) -> dict[str, Any]:
        screen = self.screen()
        if screen["screen_id"] != expected_screen:
            raise ValueError("界面已变化，请重新读取后发起操作。")
        text = " ".join(n["text"] + " " + n["description"] for n in screen["nodes"]).lower()
        if any(word.lower() in text for word in SENSITIVE):
            raise ValueError("此界面包含支付、凭证或敏感账户操作，请在手机上手动处理。")
        return screen

    def tap(self, node_id: int, expected_screen: str) -> dict[str, Any]:
        screen = self.checked(expected_screen)
        node = next((n for n in screen["nodes"] if n["id"] == node_id), None)
        if not node or not node["clickable"] or not node["enabled"]:
            raise ValueError("只能点击本次界面中可用的控件。")
        left, top, right, bottom = node["bounds"]
        contents = [
            child
            for child in screen["nodes"]
            if left <= child["bounds"][0]
            and top <= child["bounds"][1]
            and child["bounds"][2] <= right
            and child["bounds"][3] <= bottom
        ]
        labels = " ".join(child["text"] + child["description"] for child in contents).lower()
        if any(child["class"].endswith("EditText") for child in contents) or any(
            word in labels for word in ("发送", "send", "呼叫", "拨打", "通话", "call")
        ):
            raise ValueError("输入、发消息与通话不能使用通用点击工具。")
        left, top, right, bottom = node["bounds"]
        self.command("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))
        return {"status": "succeeded", "message": "点击命令已发送，请读取新界面核对效果。"}

    def open_app(self, package_name: str) -> dict[str, Any]:
        if package_name not in self.packages:
            raise ValueError("该应用不在白名单。")
        self.command(
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            "-p",
            package_name,
        )
        return {"status": "succeeded", "message": "启动命令已发送，请读取界面核对。"}

    def navigate(self, key: Literal["back", "home"]) -> dict[str, Any]:
        if key not in {"back", "home"}:
            raise ValueError("只允许返回或回桌面。")
        self.screen()  # Require an unlocked, allowlisted foreground app.
        self.command("shell", "input", "keyevent", "4" if key == "back" else "3")
        return {"status": "succeeded", "message": "导航命令已发送。"}

    def current_chat(self, contact: str, screen: dict[str, Any] | None = None) -> dict[str, Any]:
        if contact not in self.contacts:
            raise ValueError("联系人不在白名单。")
        screen = screen or self.screen()
        if screen["package"] != WECHAT:
            raise ValueError("请先在手机打开个人微信的目标聊天。")
        nodes = screen["nodes"]
        height = max((n["bounds"][3] for n in nodes), default=0)
        inputs = [
            n
            for n in nodes
            if n["class"].endswith("EditText")
            and not n["private"]
            and n["bounds"][1] > height * 0.45
        ]
        titles = [n for n in nodes if n["text"] == contact and n["bounds"][3] < height * 0.25]
        # Fail closed on groups, ambiguous titles, search screens, or changed WeChat layouts.
        if len(inputs) != 1 or len(titles) != 1:
            raise ValueError("无法确认联系人与聊天输入框，请手动打开该一对一聊天。")
        return {
            "status": "succeeded",
            "contact": contact,
            "screen_id": screen["screen_id"],
            "input": inputs[0],
            "visible_text": [
                n["text"]
                for n in nodes
                if n["text"] and titles[0]["bounds"][3] < n["bounds"][1] < inputs[0]["bounds"][1]
            ],
        }

    def send_message(self, contact: str, text: str, expected_screen: str) -> dict[str, Any]:
        if not text.strip() or len(text) > 1000 or any(ord(c) < 32 for c in text):
            raise ValueError("消息需为 1–1000 字的单行文字。")
        screen = self.checked(expected_screen)
        chat = self.current_chat(contact, screen)
        if chat["input"]["text"] and chat["input"]["text"] != text:
            raise ValueError("输入框已有其他草稿，请先在手机处理，避免覆盖。")
        if chat["input"]["text"] != text:
            ime = self.command("shell", "settings", "get", "secure", "default_input_method").strip()
            if ime != "com.android.adbkeyboard/.AdbIME":
                raise ValueError(
                    "发送文字需要手机已安装并手动选用 ADBKeyboard；不会自动切换输入法。"
                )
            left, top, right, bottom = chat["input"]["bounds"]
            self.command(
                "shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2)
            )
            encoded = base64.b64encode(text.encode()).decode("ascii")
            self.command(
                "shell",
                "am",
                "broadcast",
                "-a",
                "ADB_INPUT_B64",
                "-p",
                "com.android.adbkeyboard",
                "--es",
                "msg",
                encoded,
            )
        # Recipient and exact draft must still match immediately before clicking Send.
        fresh = self.screen()
        chat = self.current_chat(contact, fresh)
        if chat["input"]["text"] != text:
            raise ValueError("未能核对完整草稿，消息没有发送。请在手机检查。")
        send = [
            n
            for n in fresh["nodes"]
            if n["text"] in {"发送", "Send"}
            and n["enabled"]
            and n["bounds"][1] >= chat["input"]["bounds"][1] - 30
        ]
        if len(send) != 1:
            raise ValueError("无法确认发送按钮，草稿已保留，请手动检查。")
        left, top, right, bottom = send[0]["bounds"]
        self.command("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))
        try:
            after = self.current_chat(contact)
            if after["input"]["text"] or text not in after["visible_text"]:
                raise ValueError("unverified send")
        except ValueError:
            return {
                "status": "uncertain",
                "message": "已点击发送，但无法核对结果；请查看微信，勿重复发送。",
            }
        return {
            "status": "succeeded",
            "contact": contact,
            "message": "已在当前微信聊天中看到该消息；不代表对方已读。",
        }


def build_server(bridge: PhoneBridge) -> FastMCP:
    mcp = FastMCP("Companion Android and WeChat", instructions="只操作设备及应用白名单。")

    @mcp.tool()
    def phone_status() -> dict[str, Any]:
        """查看指定安卓设备的连接状态与允许操作的范围。"""
        return bridge.status()

    @mcp.tool()
    def phone_read_screen() -> dict[str, Any]:
        """读取前台白名单应用的可见 UI 控件与 screen_id。不读取后台或完整聊天记录。"""
        return bridge.screen()

    @mcp.tool()
    def phone_open_app(package_name: str) -> dict[str, Any]:
        """打开白名单中的 Android 应用。"""
        return bridge.open_app(package_name)

    @mcp.tool()
    def phone_tap(node_id: int, expected_screen: str) -> dict[str, Any]:
        """点击刚读取的界面中指定可用控件。界面变化、输入、发送和敏感操作会被拒绝。"""
        return bridge.tap(node_id, expected_screen)

    @mcp.tool()
    def phone_navigate(key: Literal["back", "home"]) -> dict[str, Any]:
        """从白名单应用返回上一页或回到桌面。"""
        return bridge.navigate(key)

    @mcp.tool()
    def wechat_read_current_chat(contact: str) -> dict[str, Any]:
        """读取手机当前打开的白名单联系人聊天的可见文字。需人工先打开目标一对一聊天。"""
        return bridge.current_chat(contact)

    @mcp.tool()
    def wechat_send_message(contact: str, text: str, expected_screen: str) -> dict[str, Any]:
        """向当前打开的白名单联系人发送明确文字。需新鲜 screen_id。

        支持已准备的相同草稿或用户预先选用的 ADBKeyboard 输入。
        返回 uncertain 时必须人工核对。不要重复发送。
        """
        return bridge.send_message(contact, text, expected_screen)

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(description="受限的安卓 / 个人微信 MCP 服务")
    parser.add_argument("--serial", required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--packages", default=WECHAT)
    parser.add_argument("--contacts", default="")
    args = parser.parse_args()
    bridge = PhoneBridge(
        args.serial,
        [p.strip() for p in args.packages.split(",") if p.strip()],
        [p.strip() for p in args.contacts.split(",") if p.strip()],
        args.adb,
    )
    build_server(bridge).run(transport="stdio")


if __name__ == "__main__":
    main()
