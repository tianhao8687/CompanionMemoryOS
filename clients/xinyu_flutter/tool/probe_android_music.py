"""Call the installed MusicBridge in an already owned local test emulator.

This is a native-only integration probe, not a Python/MCP or Flutter UI pass.
The signed instrumentation APK must already be installed by the owning driver.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--request", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"android-local-[a-f0-9]{32}", args.run_id):
        parser.error("Expected an owned Android test run ID")
    run = ROOT / ".agent-tests" / args.run_id
    receipt = json.loads((run / "results.json").read_text(encoding="utf-8"))
    serial = receipt["serial"]
    if receipt["status"] != "running" or not re.fullmatch(r"emulator-\d+", serial):
        parser.error("Run is not an active owned emulator")

    def adb(*command: str) -> str:
        return subprocess.check_output([str(args.adb), "-s", serial, *command], timeout=90).decode(
            "utf-8", "replace"
        )

    if adb("emu", "avd", "name").splitlines()[0] != args.run_id:
        parser.error("AVD ownership mismatch")
    if adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
        parser.error("Physical devices are not supported")
    request = json.loads(args.request)
    prefix = run / f"native-music-{time.time_ns()}"
    raw = adb(
        "shell",
        "am",
        "instrument",
        "-w",
        "-e",
        "run_id",
        args.run_id,
        "-e",
        "phase",
        "native_music",
        "-e",
        "request",
        shlex.quote(json.dumps(request, ensure_ascii=False)),
        "com.xinyu.smoke/.NativeProbe",
    )
    prefix.with_suffix(".log").write_text(raw, encoding="utf-8")
    line = next(
        (
            s.split("report=", 1)[1]
            for s in raw.splitlines()
            if s.startswith("INSTRUMENTATION_RESULT: report=")
        ),
        None,
    )
    if line is None:
        raise RuntimeError(f"No native result; see {prefix.with_suffix('.log')}")
    result = json.loads(line)
    package_path = adb("shell", "pm", "path", "com.xinyu.xinyu_flutter.preview").strip()
    if not package_path.startswith("package:/data/app/") or "\n" in package_path:
        raise RuntimeError("Unexpected preview installation path")
    apk_hash = adb(
        "shell", "sha256sum", shlex.quote(package_path.removeprefix("package:"))
    ).split()[0]
    evidence = {
        "scope": "installed_native_bridge",
        "apk_sha256": apk_hash,
        "request": request,
        "result": result,
    }
    prefix.with_suffix(".json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    main()
