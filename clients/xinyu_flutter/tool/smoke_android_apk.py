"""Launch the actual release APK twice on a fresh, CI-owned Android emulator.

Never attaches to a user's phone or existing app data. The emulator must support
ARM64 (including Google's documented ARM translation on x86_64 system images).
No conversations, model calls, external channels, or user credentials are used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from uuid import uuid4

PACKAGE = "com.xinyu.xinyu_flutter"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk-root", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("This acceptance driver is restricted to a fresh GitHub Actions emulator")
    root = Path(__file__).resolve().parents[3]
    run_id = "android-startup-" + uuid4().hex
    run = root / ".agent-tests" / run_id
    run.mkdir(parents=True)
    result: dict[str, object] = {
        "run_id": run_id,
        "source_commit": os.environ.get("GITHUB_SHA"),
        "status": "running",
        "android_runtime": "not_run",
        "physical_device": "not_run",
        "model_calls": 0,
    }
    serial = ""
    installed = False

    def adb(*arguments: str, timeout: int = 35) -> str:
        command = ["adb", *(["-s", serial] if serial else []), *arguments]
        response = subprocess.run(command, capture_output=True, timeout=timeout, check=True)
        return response.stdout.decode("utf-8", "replace").strip()

    try:
        candidates = list(args.apk_root.rglob("XinYu-Android-arm64.apk"))
        if len(candidates) != 1:
            raise RuntimeError("Expected exactly one release APK")
        apk = candidates[0].resolve()
        with apk.open("rb") as source:
            result["apk_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
        devices = [line.split() for line in adb("devices").splitlines()[1:] if line.strip()]
        if len(devices) != 1 or devices[0][1:] != ["device"]:
            raise RuntimeError("Expected one fresh emulator and no other attached devices")
        serial = devices[0][0]
        if not serial.startswith("emulator-") or adb("shell", "getprop", "ro.kernel.qemu") != "1":
            raise RuntimeError("Refusing to operate on a physical or unknown device")
        result["abis"] = adb("shell", "getprop", "ro.product.cpu.abilist")
        result["android_version"] = adb("shell", "getprop", "ro.build.version.release")
        if "arm64-v8a" not in str(result["abis"]).split(","):
            raise RuntimeError("This emulator image does not support the actual ARM64 release APK")
        if PACKAGE in adb("shell", "pm", "list", "packages", PACKAGE):
            raise RuntimeError("Refusing to use an existing installation or its data")
        if "Success" not in adb("install", str(apk), timeout=120):
            raise RuntimeError("APK installation did not succeed")
        installed = True
        result["android_runtime"] = "started"
        for attempt in (1, 2):
            adb("shell", "am", "start", "-W", "-n", f"{PACKAGE}/.MainActivity")
            deadline = time.monotonic() + 150
            connected = False
            while time.monotonic() < deadline:
                try:
                    adb("shell", "uiautomator", "dump", "/sdcard/xinyu-startup.xml", timeout=20)
                    hierarchy = adb("shell", "cat", "/sdcard/xinyu-startup.xml")
                except subprocess.TimeoutExpired:
                    continue
                (run / f"launch-{attempt}.xml").write_text(hierarchy, encoding="utf-8")
                if "记忆保存在本机" in hierarchy:
                    connected = True
                    break
                if "本机引擎未连接" in hierarchy:
                    break
                time.sleep(3)
            screenshot = subprocess.run(
                ["adb", "-s", serial, "exec-out", "screencap", "-p"],
                capture_output=True,
                check=True,
                timeout=20,
            ).stdout
            (run / f"launch-{attempt}.png").write_bytes(screenshot)
            result[f"launch_{attempt}_connected"] = connected
            if not connected:
                raise RuntimeError(f"Release APK did not connect to its engine on launch {attempt}")
            adb("shell", "am", "force-stop", PACKAGE)
        result["android_runtime"] = "startup_and_restart_passed"
        result["status"] = "passed"
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        result["status"] = "failed"
        result["error"] = str(error)
        return 1
    finally:
        if installed:
            try:
                log = adb("logcat", "-d", "-s", "XinYuEngine:E", "AndroidRuntime:E")
                (run / "startup.log").write_text(log, encoding="utf-8")
                adb("shell", "am", "force-stop", PACKAGE)
            except (OSError, subprocess.SubprocessError):
                result["cleanup"] = "emulator runner must stop its owned process"
        (run / "results.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"Run ID: {run_id}; status: {result['status']}; report: {run / 'results.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
