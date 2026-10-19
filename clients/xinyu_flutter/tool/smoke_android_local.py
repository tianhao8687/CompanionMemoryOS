"""Exercise a release APK in a newly created, owned local Android emulator.

Never attaches to an existing emulator or physical phone. Each run gets a fresh
AVD and synthetic app data. No model, account, or external-service calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

PACKAGE = "com.xinyu.xinyu_flutter.preview"
ACTIVITY = "com.xinyu.xinyu_flutter.MainActivity"
ROOT = Path(__file__).resolve().parents[3]


class LocalRun:
    def __init__(self, sdk: Path, adb: Path, workspace: Path, apk: Path, api: int = 35) -> None:
        self.id = "android-local-" + uuid4().hex
        self.run = ROOT / ".agent-tests" / self.id
        self.run.mkdir(parents=True)
        self.avd = workspace.resolve() / self.id
        self.avd.mkdir(parents=True, exist_ok=False)
        self.sdk, self.adb_path, self.apk = sdk.resolve(), adb.resolve(), apk.resolve()
        if api not in {30, 33, 35}:
            raise ValueError("Only the verified API 30, 33 and 35 test images are supported")
        self.api = api
        self.process: subprocess.Popen | None = None
        self.logcat: subprocess.Popen | None = None
        self.serial = ""
        self.sequence = 0
        self.result = {
            "run_id": self.id,
            "status": "running",
            "apk_sha256": hashlib.sha256(self.apk.read_bytes()).hexdigest(),
            "test_driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "package": PACKAGE,
            "avd": str(self.avd),
            "model_calls": 0,
            "physical_device": "not_run",
            "real_netease_playback": "not_run",
            "checks": [],
        }
        self.save()

    def save(self) -> None:
        (self.run / "results.json").write_text(
            json.dumps(self.result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def record(self, name: str, **detail: object) -> None:
        self.result["checks"].append({"name": name, "status": "passed", **detail})
        self.save()
        print(f"PASS {name}", flush=True)

    def adb(self, *args: str, timeout: int = 30, binary: bool = False) -> str | bytes:
        if not self.process or self.process.poll() is not None or not self.serial:
            raise RuntimeError("Owned emulator is not running")
        completed = subprocess.run(
            [str(self.adb_path), "-s", self.serial, *args],
            capture_output=True,
            timeout=timeout,
        )
        if completed.returncode:
            detail = (completed.stdout + completed.stderr).decode("utf-8", "replace")
            raise RuntimeError(f"adb {args[:4]} exited {completed.returncode}: {detail[-2500:]}")
        output = completed.stdout
        return output if binary else output.decode("utf-8", "replace").strip()

    def boot(self) -> None:
        for port in range(5580, 5600, 2):
            try:
                with socket.socket() as first, socket.socket() as second:
                    first.bind(("127.0.0.1", port))
                    second.bind(("127.0.0.1", port + 1))
                break
            except OSError:
                continue
        else:
            raise RuntimeError("No unused emulator ports")
        self.serial = f"emulator-{port}"
        image = self.sdk / f"system-images/android-{self.api}/google_apis/x86_64"
        if not (image / "system.img").is_file():
            raise RuntimeError(
                f"Install the official API {self.api} Google APIs x86_64 image first"
            )
        data = self.avd / f"{self.id}.avd"
        data.mkdir()
        (self.avd / f"{self.id}.ini").write_text(
            f"avd.ini.encoding=UTF-8\npath={data}\ntarget=android-{self.api}\n", encoding="utf-8"
        )
        (data / "config.ini").write_text(
            "\n".join(
                [
                    f"AvdId={self.id}",
                    "abi.type=x86_64",
                    "hw.cpu.arch=x86_64",
                    "hw.cpu.ncore=4",
                    "hw.ramSize=4096",
                    "hw.lcd.width=1080",
                    "hw.lcd.height=1920",
                    "hw.lcd.density=420",
                    "hw.gpu.enabled=yes",
                    "hw.gpu.mode=host",
                    "hw.keyboard=yes",
                    "hw.audioInput=no",
                    "hw.camera.back=none",
                    "hw.camera.front=none",
                    "disk.dataPartition.size=4G",
                    "tag.id=google_apis",
                    "tag.display=Google APIs",
                    f"image.sysdir.1={image.as_posix()}/",
                    "showDeviceFrame=no",
                    "PlayStore.enabled=false",
                    "fastboot.forceColdBoot=yes",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        env = {**os.environ, "ANDROID_AVD_HOME": str(self.avd), "ANDROID_HOME": str(self.sdk)}
        log = (self.run / "emulator.log").open("wb")
        try:
            self.process = subprocess.Popen(
                [
                    str(self.sdk / "emulator/emulator.exe"),
                    "-avd",
                    self.id,
                    "-port",
                    str(port),
                    "-no-window",
                    "-no-snapshot",
                    "-no-audio",
                    "-no-boot-anim",
                    "-gpu",
                    "host",
                    "-feature",
                    "-Vulkan",
                    "-accel",
                    "on",
                ],
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        finally:
            log.close()
        self.result["emulator_pid"] = self.process.pid
        self.result["serial"] = self.serial
        self.save()
        print(f"Run ID: {self.id}; waiting for owned emulator", flush=True)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                if self.adb("shell", "getprop", "sys.boot_completed", timeout=10) == "1":
                    break
            except (RuntimeError, subprocess.SubprocessError):
                pass
            time.sleep(3)
        else:
            raise RuntimeError("Emulator boot timed out")
        if self.adb("shell", "getprop", "ro.kernel.qemu") != "1":
            raise RuntimeError("Not an emulator")
        avd_name = self.adb("emu", "avd", "name").splitlines()[0]
        if avd_name != self.id:
            raise RuntimeError("Emulator ownership mismatch")
        abis = self.adb("shell", "getprop", "ro.product.cpu.abilist")
        if "arm64-v8a" not in abis.split(","):
            raise RuntimeError(f"Image cannot run the delivered ARM64 APK: {abis}")
        self.record(
            "owned_emulator",
            abis=abis,
            android=self.adb("shell", "getprop", "ro.build.version.release"),
        )
        for setting in (
            "window_animation_scale",
            "transition_animation_scale",
            "animator_duration_scale",
        ):
            self.adb("shell", "settings", "put", "global", setting, "0")
        self.adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
        self.adb("shell", "wm", "dismiss-keyguard")
        with (self.run / "device.log").open("wb") as log:
            self.logcat = subprocess.Popen(
                [str(self.adb_path), "-s", self.serial, "logcat", "-v", "threadtime", "-b", "all"],
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

    def hierarchy(self, label: str = "ui") -> ET.Element:
        self.sequence += 1
        path = f"/sdcard/xinyu-owned-smoke-{self.sequence}-{time.time_ns()}.xml"
        output = self.adb("shell", "uiautomator", "dump", path, timeout=20)
        if "dumped to:" not in output:
            raise RuntimeError(f"Fresh UI hierarchy unavailable: {output}")
        text = self.adb("shell", "cat", path)
        (self.run / f"{self.sequence:03}-{label}.xml").write_text(text, encoding="utf-8")
        return ET.fromstring(text)

    def screenshot(self, label: str) -> None:
        (self.run / f"{label}.png").write_bytes(
            self.adb("exec-out", "screencap", "-p", binary=True)
        )

    @staticmethod
    def label(node: ET.Element) -> str:
        return node.get("content-desc", "") or node.get("text", "")

    def find(self, label: str, scroll: int = 0) -> ET.Element:
        for attempt in range(scroll + 1):
            root = self.hierarchy()
            nodes = [
                n
                for n in root.iter("node")
                if label == self.label(n)
                or label in self.label(n).split("\n")
                or self.label(n).startswith(label + ", ")
            ]
            if nodes:
                return nodes[0]
            if attempt < scroll:
                self.adb("shell", "input", "swipe", "530", "1530", "530", "620", "350")
        labels = [self.label(n) for n in root.iter("node") if self.label(n)]
        raise RuntimeError(f"Control not found: {label}; visible: {labels}")

    def tap(self, label: str, scroll: int = 0) -> None:
        node = self.find(label, scroll)
        self.tap_node(node)

    def tap_node(self, node: ET.Element) -> None:
        if node.get("enabled") != "true":
            raise RuntimeError(f"Control disabled: {self.label(node)}")
        x1, y1, x2, y2 = map(int, re.findall(r"\d+", node.get("bounds", "")))
        self.adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
        time.sleep(0.5)

    def set_switch(self, label: str, checked: bool) -> None:
        # Flutter can expose the clipped edge of a tall SwitchListTile. Bring the
        # entire tap target into the body, away from the fixed header/footer.
        for _ in range(8):
            node = self.find(label, scroll=6)
            _, top, _, bottom = map(int, re.findall(r"\d+", node.get("bounds", "")))
            if top >= 350 and bottom <= 1500:
                break
            start, end = (1400, 850) if bottom > 1500 else (650, 1050)
            self.adb("shell", "input", "swipe", "530", str(start), "530", str(end), "350")
            time.sleep(0.4)
        else:
            raise RuntimeError(f"Switch not fully visible: {label}")
        desired = "true" if checked else "false"
        if node.get("checked") == desired:
            return
        self.tap_node(node)
        # Poll observations only. Never toggle a second time after an uncertain tap.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            root = self.hierarchy()
            if any(
                label in self.label(n).split("\n") and n.get("checked") == desired
                for n in root.iter("node")
            ):
                return
            time.sleep(0.5)
        raise RuntimeError(f"Switch did not reach {desired}: {label}")

    def row_button(self, title: str, button: str) -> None:
        title_node = self.find(title, scroll=8)
        title_bounds = list(map(int, re.findall(r"\d+", title_node.get("bounds", ""))))
        root = self.hierarchy()
        choices = [n for n in root.iter("node") if self.label(n) == button]
        if not choices:
            raise RuntimeError(f"Missing button {button} for {title}")
        node = min(
            choices,
            key=lambda n: abs(int(re.findall(r"\d+", n.get("bounds", ""))[1]) - title_bounds[1]),
        )
        self.tap_node(node)

    def scroll_top(self) -> None:
        for _ in range(5):
            self.adb("shell", "input", "swipe", "530", "650", "530", "1540", "250")

    def wait_ready(self, label: str) -> None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                hierarchy = self.hierarchy(label)
                if any(
                    n.get("resource-id") in {"xinyu-local-ready", f"{PACKAGE}:id/xinyu-local-ready"}
                    and n.get("package") == PACKAGE
                    and n.get("enabled") == "true"
                    for n in hierarchy.iter("node")
                ):
                    self.screenshot(label)
                    return
            except (subprocess.SubprocessError, ET.ParseError):
                pass
            except RuntimeError as error:
                if not str(error).startswith("Fresh UI hierarchy unavailable:"):
                    raise
            time.sleep(2)
        raise RuntimeError(f"Release APK did not connect to embedded engine: {label}")

    def startup(self) -> None:
        if PACKAGE in self.adb("shell", "pm", "list", "packages", PACKAGE):
            raise RuntimeError("Refusing an existing installation")
        if "Success" not in self.adb("install", str(self.apk), timeout=150):
            raise RuntimeError("APK install failed")
        for attempt in (1, 2):
            start = time.monotonic()
            self.adb("shell", "am", "start", "-W", "-n", f"{PACKAGE}/{ACTIVITY}", timeout=45)
            self.wait_ready(f"launch-{attempt}")
            self.record(
                f"launch_{attempt}_engine_connected", seconds=round(time.monotonic() - start, 2)
            )
            if attempt == 1:
                self.adb("shell", "am", "force-stop", PACKAGE)

    def connections(self) -> None:
        self.tap("陪伴设置")
        self.tap("连接")
        self.find("网易云音乐")
        self.find("手机能力", scroll=10)
        self.screenshot("connections-before")
        self.record("phone_and_music_connection_page")
        self.row_button("手机能力", "连接")
        time.sleep(2)
        self.scroll_top()
        self.find("已连接 · 在这台手机上执行", scroll=4)
        self.screenshot("phone-connected")
        self.record("phone_connection_via_ui")
        self.set_switch("聊天中的手机陪伴", True)
        self.find("声音轻一点", scroll=4)
        self.set_switch("屏幕柔和一点", True)
        self.find("留一会儿安静", scroll=4)
        self.screenshot("phone-companion-enabled")
        self.record("phone_companion_scope_via_ui")
        self.scroll_top()
        self.set_switch("聊天中的手机陪伴", False)
        self.record("phone_companion_disabled_via_ui")
        self.scroll_top()
        self.row_button("网易云音乐", "连接")
        time.sleep(2)
        self.scroll_top()
        self.find("AI 操作权限", scroll=3)
        self.record("music_connection_via_ui")
        self.find("已连接 · 在这台手机上执行", scroll=4)
        self.record("music_connection_preserves_phone")
        self.tap("手机权限与使用说明", scroll=8)
        self.find("修改系统设置 · 调整亮度", scroll=4)
        self.screenshot("phone-permissions")
        self.record("permission_help_visible")
        title = "修改系统设置 · 调整亮度"
        self.row_button(title, "去授权")
        self.tap("Allow modifying system settings")
        self.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)
        self.find("已授权，可在系统设置中撤销", scroll=2)
        self.record("system_permission_grant_refreshes_ui")
        self.row_button(title, "管理")
        self.tap("Allow modifying system settings")
        self.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)
        self.row_button(title, "去授权")
        self.adb("shell", "input", "keyevent", "KEYCODE_BACK")
        self.record("system_permission_revoke_refreshes_ui")

    def native(self, probe: Path, phases: list[str] | None = None) -> None:
        first_check = len(self.result["checks"])
        self.result["probe_sha256"] = hashlib.sha256(probe.read_bytes()).hexdigest()
        if "Success" not in self.adb("install", str(probe.resolve()), timeout=60):
            raise RuntimeError("Native probe installation failed")
        metadata_raw = self.adb(
            "shell",
            "am",
            "instrument",
            "-w",
            "-e",
            "run_id",
            self.id,
            "-e",
            "phase",
            "sensor_metadata",
            "com.xinyu.smoke/.NativeProbe",
            timeout=40,
        )
        line = next(
            line
            for line in metadata_raw.splitlines()
            if line.startswith("INSTRUMENTATION_RESULT: report=")
        )
        metadata = json.loads(line.split("report=", 1)[1])
        if not metadata["light"]["available"] or not metadata["proximity"]["available"]:
            raise RuntimeError(f"Owned emulator lacks test sensors: {metadata}")
        self.record("emulator_sensor_capabilities", **metadata)
        for phase in phases or [
            "base",
            "granted",
            "environment_dim",
            "environment_bright",
            "environment_covered",
            "environment_auto",
            "environment_background",
            "revoked",
        ]:
            if phase == "granted":
                self.adb("shell", "appops", "set", PACKAGE, "WRITE_SETTINGS", "allow")
                self.adb("shell", "cmd", "notification", "allow_dnd", PACKAGE)
                self.adb(
                    "shell",
                    "settings",
                    "put",
                    "secure",
                    "enabled_accessibility_services",
                    f"{PACKAGE}/com.xinyu.xinyu_flutter.PhoneAccessibilityService",
                )
                self.adb("shell", "settings", "put", "secure", "accessibility_enabled", "1")
                self.adb("shell", "am", "start", "-W", "-n", "com.xinyu.smoke/.FixtureActivity")
                time.sleep(2)
            elif phase == "revoked":
                self.adb("shell", "appops", "set", PACKAGE, "WRITE_SETTINGS", "deny")
                self.adb("shell", "cmd", "notification", "disallow_dnd", PACKAGE)
                self.adb("shell", "settings", "delete", "secure", "enabled_accessibility_services")
                self.adb("shell", "settings", "put", "secure", "accessibility_enabled", "0")
            if phase.startswith("environment_"):
                lux = "20000" if phase == "environment_bright" else "8"
                self.adb("shell", "appops", "set", PACKAGE, "WRITE_SETTINGS", "allow")
                proximity = (
                    "0"
                    if phase == "environment_covered"
                    else str(metadata["proximity"]["maximum_range"])
                )
                self.adb("emu", "sensor", "set", "light", lux)
                self.adb("emu", "sensor", "set", "proximity", proximity)
                self.record(
                    "emulator_sensor_inputs_" + phase,
                    light=self.adb("emu", "sensor", "get", "light"),
                    proximity=self.adb("emu", "sensor", "get", "proximity"),
                )
            raw = self.adb(
                "shell",
                "am",
                "instrument",
                "-w",
                "-e",
                "run_id",
                self.id,
                "-e",
                "phase",
                phase,
                "-e",
                "foreground",
                "1"
                if phase.startswith("environment_") and phase != "environment_background"
                else "0",
                "com.xinyu.smoke/.NativeProbe",
                timeout=150,
            )
            (self.run / f"probe-{phase}.log").write_text(raw, encoding="utf-8")
            report_line = next(
                (
                    line
                    for line in raw.splitlines()
                    if line.startswith("INSTRUMENTATION_RESULT: report=")
                ),
                None,
            )
            if not report_line:
                raise RuntimeError(f"Native probe did not return a report: {raw[-2500:]}")
            report = json.loads(report_line.split("report=", 1)[1])
            (self.run / f"probe-{phase}.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.result["checks"].extend({**check, "phase": phase} for check in report["checks"])
            self.save()
            print(
                f"Native phase {phase}: "
                + ", ".join(f"{c['name']}={c['status']}" for c in report["checks"]),
                flush=True,
            )
        failures = [c for c in self.result["checks"][first_check:] if c["status"] != "passed"]
        if failures:
            raise RuntimeError(f"Native checks failed: {[c['name'] for c in failures]}")

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            with suppress(OSError, RuntimeError, subprocess.SubprocessError):
                self.screenshot("final")
            try:
                self.adb("emu", "kill")
                self.process.wait(timeout=20)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                self.process.terminate()
        if self.logcat and self.logcat.poll() is None:
            self.logcat.terminate()
        self.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, required=True)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--avd-workspace", type=Path, required=True)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--probe-apk", type=Path)
    parser.add_argument(
        "--native-only",
        action="store_true",
        help="Skip connection UI during targeted native diagnosis",
    )
    parser.add_argument(
        "--native-phases",
        nargs="+",
        choices=[
            "base",
            "granted",
            "environment_dim",
            "environment_bright",
            "environment_covered",
            "environment_auto",
            "environment_background",
            "revoked",
        ],
    )
    args = parser.parse_args()
    if (args.native_only or args.native_phases) and not args.probe_apk:
        parser.error("Native options require --probe-apk")
    run = LocalRun(args.sdk, args.adb, args.avd_workspace, args.apk)
    try:
        run.boot()
        run.startup()
        stages = [] if args.native_only else [("connection_ui", run.connections)]
        if args.probe_apk:
            stages.append(
                ("native_runtime", lambda: run.native(args.probe_apk, args.native_phases))
            )
        for name, action in stages:
            try:
                action()
            except Exception as error:
                run.result["checks"].append({"name": name, "status": "failed", "error": str(error)})
                run.screenshot(name + "-failed")
                run.save()
                print(f"FAIL {name}: {error}", flush=True)
        failed = any(check["status"] == "failed" for check in run.result["checks"])
        run.result["status"] = "failed" if failed else "passed"
        return 1 if failed else 0
    except Exception as error:
        run.result["status"] = "failed"
        run.result["error"] = f"{type(error).__name__}: {error}"
        print(run.result["error"], flush=True)
        return 1
    finally:
        run.close()
        print(f"Run ID: {run.id}; status: {run.result['status']}; report: {run.run}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
