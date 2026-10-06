"""Build the three missing CPython 3.13 Android wheels on Linux/macOS.

Use a separate build host with Python 3.12+, Java 21 and an Android SDK. Install
cibuildwheel==4.2.1 into its build environment. This downloads official PyPI
source archives, verifies their published SHA-256 hashes, then lets cibuildwheel
provision its Android/Rust toolchains. It never retags a desktop wheel.

This is a build step, not an Android application/device acceptance test.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from probe_android_engine import inspect_native_wheels

PACKAGES = {"pydantic-core": "2.46.5", "rpds-py": "2026.6.3", "tiktoken": "0.14.0"}
BUILDER_VERSION = "4.2.1"


def prerequisites() -> list[str]:
    errors = []
    if sys.platform not in {"linux", "darwin"}:
        errors.append("cibuildwheel's Android builder requires Linux or macOS.")
    try:
        if importlib.metadata.version("cibuildwheel") != BUILDER_VERSION:
            errors.append(f"Install cibuildwheel=={BUILDER_VERSION} in this Python environment.")
    except importlib.metadata.PackageNotFoundError:
        errors.append(f"Install cibuildwheel=={BUILDER_VERSION} in this Python environment.")
    if not os.environ.get("ANDROID_HOME"):
        errors.append("Set ANDROID_HOME to the build host's Android SDK.")
    if not shutil.which("java"):
        errors.append("Put Java 21 on PATH.")
    return errors


def download_sdist(name: str, version: str, directory: Path) -> dict[str, str]:
    with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{version}/json", timeout=60) as r:
        metadata = json.load(r)
    candidates = [item for item in metadata["urls"] if item["packagetype"] == "sdist"]
    if len(candidates) != 1:
        raise RuntimeError(f"Expected one source archive for {name}=={version}.")
    item = candidates[0]
    filename = item["filename"]
    if Path(filename).name != filename or not filename.endswith(".tar.gz"):
        raise RuntimeError("Unexpected source archive filename.")
    if not item["url"].startswith("https://files.pythonhosted.org/"):
        raise RuntimeError("Unexpected source archive host.")
    path = directory / filename
    digest = hashlib.sha256()
    with urllib.request.urlopen(item["url"], timeout=60) as response, path.open("xb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != item["digests"]["sha256"]:
        raise RuntimeError(f"SHA-256 mismatch for {filename}; download retained for diagnosis.")
    return {"package": name, "version": version, "file": str(path), "sha256": digest.hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="New/empty directory for verified wheels")
    parser.add_argument("--check", action="store_true", help="Check this host without downloading")
    args = parser.parse_args()
    errors = prerequisites()
    if errors or args.check:
        print(json.dumps({"host": platform.platform(), "ready": not errors, "reasons": errors}))
        return 2 if errors else 0
    if args.output is None:
        parser.error("--output is required")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("--output must be empty; existing wheels are never silently replaced")
    output.mkdir(parents=True, exist_ok=True)
    repository = Path(__file__).resolve().parents[3]
    run_id = "android-wheels-" + uuid4().hex
    run = repository / ".agent-tests" / run_id
    run.mkdir(parents=True)
    report: dict[str, object] = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "building",
        "builder": f"cibuildwheel=={BUILDER_VERSION}",
        "target": "cp313-android_arm64_v8a",
        "android_apk": "not_run",
        "android_runtime": "not_run",
        "model_calls": 0,
    }
    sources: list[dict[str, str]] = []
    report["sources"] = sources
    config = run / "cibuildwheel.toml"
    config.write_text(
        '[tool.cibuildwheel]\nbuild = "cp313-android_arm64_v8a"\n'
        '[tool.cibuildwheel.android]\narchs = ["arm64_v8a"]\n'
        '[tool.cibuildwheel.android.environment]\nANDROID_API_LEVEL = "24"\n'
        'RUSTFLAGS = "-C link-arg=-Wl,-z,max-page-size=16384"\n',
        encoding="utf-8",
    )
    wheelhouse = run / "wheels"
    wheelhouse.mkdir()
    try:
        for name, version in PACKAGES.items():
            source = download_sdist(name, version, run)
            sources.append(source)
            command = [
                sys.executable,
                "-m",
                "cibuildwheel",
                source["file"],
                "--platform",
                "android",
                "--config-file",
                str(config),
                "--output-dir",
                str(wheelhouse),
            ]
            print(f"Building {name}=={version}; log: {run / (name + '.log')}", flush=True)
            env = {key: value for key, value in os.environ.items() if not key.startswith("CIBW_")}
            with (run / f"{name}.log").open("w", encoding="utf-8") as log:
                subprocess.run(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    timeout=3600,
                    check=True,
                )
        wheels = sorted(wheelhouse.glob("*.whl"))
        if len(wheels) != len(PACKAGES) or any(
            "android_" not in wheel.name or "arm64_v8a" not in wheel.name for wheel in wheels
        ):
            raise RuntimeError("Builder did not produce the three expected Android ARM64 wheels.")
        libraries = inspect_native_wheels(wheelhouse)
        report["libraries"] = libraries
        if len(libraries) < len(PACKAGES) or any(
            row.get("elf_machine") != 183 or not row.get("all_load_alignments_at_least_16k")
            for row in libraries
        ):
            raise RuntimeError("Native libraries failed the ARM64 / 16-KB ELF header check.")
        report["wheels"] = [
            {"name": wheel.name, "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest()}
            for wheel in wheels
        ]
        for wheel in wheels:
            shutil.copy2(wheel, output / wheel.name)
        report["status"] = "built_runtime_unverified"
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
        return 1
    finally:
        (run / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Run ID: {run_id}; status: {report['status']}; report: {run / 'results.json'}")


if __name__ == "__main__":
    raise SystemExit(main())
