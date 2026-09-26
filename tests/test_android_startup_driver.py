from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DRIVER = Path(__file__).parents[1] / "clients/xinyu_flutter/tool/smoke_android_apk.py"


def run_driver(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, launch: str, ready: bool):
    spec = importlib.util.spec_from_file_location("android_startup_driver", DRIVER)
    assert spec and spec.loader
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    # All artifacts are synthetic unit-test evidence, not device acceptance.
    driver.__file__ = str(tmp_path / "clients/xinyu_flutter/tool/smoke_android_apk.py")
    apk_root = tmp_path / "install"
    apk_root.mkdir()
    (apk_root / "XinYu-Android-arm64.apk").write_bytes(b"synthetic APK placeholder")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr(sys, "argv", ["smoke_android_apk.py", "--apk-root", str(apk_root)])
    clock = [0.0]
    state = {"launches": 0, "ui_reads": 0}

    def monotonic():
        clock[0] += 10
        return clock[0]

    def execute(command, **_kwargs):
        if command == ["adb", "devices"]:
            output = "List of devices attached\nemulator-5554\tdevice\n"
        else:
            assert command[:3] == ["adb", "-s", "emulator-5554"]
            args = command[3:]
            if args[:2] == ["shell", "getprop"]:
                output = {
                    "ro.kernel.qemu": "1",
                    "ro.product.cpu.abilist": "x86_64,arm64-v8a",
                    "ro.build.version.release": "15",
                }[args[2]]
            elif args[:3] == ["shell", "pm", "list"]:
                output = ""
            elif args[0] == "install":
                output = "Success"
            elif args[:3] == ["shell", "am", "start"]:
                state["launches"] += 1
                output = launch
            elif args[:3] == ["shell", "uiautomator", "dump"]:
                output = "UI hierarchy dumped"
            elif args[:2] == ["shell", "cat"]:
                state["ui_reads"] += 1
                # A real disconnected header can appear before initialization ends.
                label = "记忆保存在本机" if ready and state["ui_reads"] > 1 else "本机引擎未连接"
                output = f'<hierarchy><node text="{label}" /></hierarchy>'
            elif args[:2] == ["exec-out", "screencap"]:
                output = "synthetic screenshot placeholder"
            elif args[0] == "logcat" or args[:3] == ["shell", "am", "force-stop"]:
                output = ""
            else:
                raise AssertionError(f"Unexpected command: {command}")
        return subprocess.CompletedProcess(command, 0, stdout=output.encode(), stderr=b"")

    driver.time = SimpleNamespace(monotonic=monotonic, sleep=lambda _: None)
    driver.subprocess = SimpleNamespace(
        run=execute,
        SubprocessError=subprocess.SubprocessError,
        TimeoutExpired=subprocess.TimeoutExpired,
    )
    code = driver.main()
    reports = list((tmp_path / ".agent-tests").glob("android-startup-*/results.json"))
    assert len(reports) == 1
    return code, json.loads(reports[0].read_text(encoding="utf-8")), state


def test_cold_launch_timeout_still_requires_connected_ui_on_both_launches(monkeypatch, tmp_path):
    # Replays the command outcome from run android-startup-887f6053f39e43c69d88d051d4d53f4d.
    code, report, state = run_driver(
        monkeypatch,
        tmp_path,
        launch="Status: timeout\nActivity: com.xinyu.xinyu_flutter/.MainActivity\nComplete",
        ready=True,
    )
    assert code == 0
    assert report["android_runtime"] == "startup_and_restart_passed"
    assert report["launch_1_connected"] and report["launch_2_connected"]
    assert state == {"launches": 2, "ui_reads": 3}


def test_activity_launch_success_without_engine_connection_is_a_failure(monkeypatch, tmp_path):
    code, report, state = run_driver(monkeypatch, tmp_path, launch="Status: ok", ready=False)
    assert code == 1
    assert report["status"] == "failed"
    assert report["launch_1_connected"] is False
    assert state["launches"] == 1 and state["ui_reads"] > 1


def test_activity_command_error_never_reaches_the_ui_success_check(monkeypatch, tmp_path):
    code, report, state = run_driver(
        monkeypatch, tmp_path, launch="Error: Activity class does not exist.", ready=True
    )
    assert code == 1
    assert report["status"] == "failed"
    assert state["ui_reads"] == 0
