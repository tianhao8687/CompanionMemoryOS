"""Probe Android wheel availability without installing or altering the app.

This is a dependency gate, not an Android build or device acceptance test.
Only public package metadata/wheels are downloaded. No model calls are made.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

PYPI = "https://pypi.org/simple"
CHAQUOPY = "https://chaquo.com/pypi-13.1/"
# Individual candidates, deliberately not a claim that the complete graph resolves.
# Native dependency lower bounds follow the current project's Pydantic 2 /
# jsonschema / tiktoken requirements; no Pydantic 1 or approximate tokenizer fallback.
CANDIDATES = {
    "pydantic": "pydantic>=2.10,<3",
    "pydantic-core": "pydantic-core>=2.27,<3",
    "tiktoken": "tiktoken>=0.9,<1",
    "rpds-py": "rpds-py>=0.7",
    "regex": "regex>=2022.1.18",
    "pyyaml": "PyYAML>=6,<7",
    "mcp": "mcp>=1.30,<2",
    "tzdata": "tzdata>=2025.1",
}
NETWORK_ERRORS = (
    "could not fetch url",
    "connectionerror",
    "connecttimeout",
    "readtimeout",
    "proxyerror",
    "sslerror",
    "certificate_verify_failed",
    "failed to establish",
    "network is unreachable",
    "temporary failure",
    "retrying (retry",
)


def inspect_native_wheels(directory: Path) -> list[dict[str, object]]:
    """Read ELF load alignment only. Do not extract or execute downloaded code."""
    libraries: list[dict[str, object]] = []
    for wheel in sorted(directory.rglob("*.whl")):
        with ZipFile(wheel) as archive:
            for name in archive.namelist():
                if not name.endswith(".so"):
                    continue
                record: dict[str, object] = {"wheel": wheel.name, "library": name}
                with archive.open(name) as stream:
                    header = stream.read(64)
                    if len(header) < 64 or header[:6] != b"\x7fELF\x02\x01":
                        record["status"] = "unverified_elf_format"
                        libraries.append(record)
                        continue
                    offset = struct.unpack_from("<Q", header, 32)[0]
                    size, count = struct.unpack_from("<HH", header, 54)
                    if size < 56 or count > 1024 or offset > 1024 * 1024:
                        record["status"] = "unverified_program_headers"
                        libraries.append(record)
                        continue
                    stream.seek(offset)
                    table = stream.read(size * count)
                    if len(table) != size * count:
                        record["status"] = "unverified_truncated_program_headers"
                        libraries.append(record)
                        continue
                    alignments = [
                        struct.unpack_from("<Q", table, index * size + 48)[0]
                        for index in range(count)
                        if struct.unpack_from("<I", table, index * size)[0] == 1
                    ]
                    record.update(
                        status="headers_inspected_runtime_unverified",
                        elf_machine=struct.unpack_from("<H", header, 18)[0],
                        load_alignments=alignments,
                        all_load_alignments_at_least_16k=bool(alignments)
                        and all(alignment >= 16384 for alignment in alignments),
                    )
                    libraries.append(record)
    return libraries


def classify_result(returncode: int, output: str, wheels: list[str]) -> str:
    lowered = output.lower()
    if any(marker in lowered for marker in NETWORK_ERRORS):
        return "unverified_network_error"
    if returncode == 0 and wheels:
        # Never mistake a Windows or manylinux build for an Android candidate.
        for wheel in wheels:
            platform = wheel.removesuffix(".whl").rsplit("-", 1)[-1]
            if platform != "any" and not all(
                tag.startswith("android_") for tag in platform.split(".")
            ):
                return "invalid_target_wheel"
        return "candidate_found"
    if "no matching distribution found" in lowered:
        return "no_compatible_binary"
    return "unverified_pip_error"


def probe(
    name: str, requirement: str, python_version: str, abi: str, run_dir: Path
) -> dict[str, object]:
    target_dir = run_dir / f"python-{python_version}-{abi}" / name
    target_dir.mkdir(parents=True)
    command = [
        sys.executable,
        "-m",
        "pip",
        "--isolated",
        "--disable-pip-version-check",
        "download",
        "--index-url",
        PYPI,
        "--extra-index-url",
        CHAQUOPY,
        "--only-binary=:all:",
        "--no-deps",
        "--no-cache-dir",
        "--timeout",
        "12",
        "--retries",
        "0",
        "--implementation",
        "cp",
        "--python-version",
        python_version,
        "--abi",
        "cp" + python_version.replace(".", ""),
        "--abi",
        "abi3",
        "--abi",
        "none",
    ]
    # API-21 binaries can run on a minimum-24 app. A newer minimum must be
    # deliberately evaluated separately, never silently substituted.
    for api in range(21, 25):
        command.extend(["--platform", f"android_{api}_{abi}"])
    command.extend(["--dest", str(target_dir), requirement])
    (target_dir / "command.json").write_text(
        json.dumps(command, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output = result.stdout + result.stderr
        returncode: int | None = result.returncode
        wheels = sorted(path.name for path in target_dir.glob("*.whl"))
        status = classify_result(result.returncode, output, wheels)
    except subprocess.TimeoutExpired as error:
        chunks = [error.stdout or b"", error.stderr or b""]
        output = "".join(
            part.decode("utf-8", errors="replace") if isinstance(part, bytes) else part
            for part in chunks
        )
        output += "\nProbe stopped at its 90-second deadline.\n"
        returncode, wheels, status = None, [], "unverified_timeout"
    (target_dir / "pip.log").write_text(output, encoding="utf-8")
    finding = {
        "package": name,
        "requirement": requirement,
        "python": python_version,
        "abi": abi,
        "status": status,
        "returncode": returncode,
        "wheels": wheels,
        "log": str((target_dir / "pip.log").relative_to(run_dir)),
    }
    print(f"Python {python_version} / {name}: {status}", flush=True)
    return finding


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-version", nargs="+", choices=["3.12", "3.13"])
    parser.add_argument("--abi", choices=["arm64_v8a", "x86_64"], default="arm64_v8a")
    parser.add_argument("--inspect-wheels-in", type=Path, help="Inspect existing wheels only")
    args = parser.parse_args()
    if args.inspect_wheels_in:
        if not args.inspect_wheels_in.is_dir():
            parser.error("--inspect-wheels-in must name an existing directory")
        print(json.dumps(inspect_native_wheels(args.inspect_wheels_in), indent=2))
        return 0
    versions = list(dict.fromkeys(args.python_version or ["3.12", "3.13"]))
    repository = Path(__file__).resolve().parents[3]
    run_id = "android-engine-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    run_dir = repository / ".agent-tests" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    print(f"Run ID: {run_id}", flush=True)
    jobs = [
        (name, requirement, version, args.abi, run_dir)
        for version in versions
        for name, requirement in CANDIDATES.items()
    ]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(probe, *job) for job in jobs]
        findings = [future.result() for future in futures]
    native_libraries = inspect_native_wheels(run_dir)
    (run_dir / "elf-inspection.json").write_text(
        json.dumps(native_libraries, indent=2) + "\n", encoding="utf-8"
    )
    status = (
        "blocked_missing_binaries"
        if any(row["status"] == "no_compatible_binary" for row in findings)
        else "unverified"
        if any(row["status"] != "candidate_found" for row in findings)
        else "candidates_only_runtime_unverified"
    )
    report = {
        "run_id": run_id,
        "kind": "android_dependency_probe",
        "status": status,
        "created_at": datetime.now(UTC).isoformat(),
        "sources": [PYPI, CHAQUOPY],
        "minimum_android_api": 24,
        "tooling_on_path": {name: shutil.which(name) for name in ["flutter", "java", "adb"]},
        "model_calls": 0,
        "read_user_database": False,
        "android_build": "not_run",
        "android_runtime": "not_run",
        "full_dependency_resolution": "not_run",
        "findings": findings,
        "native_libraries": native_libraries,
        "limits": [
            "Individual wheel candidates only; no combined dependency resolution.",
            "No Android build, emulator, phone, performance or language-quality pass.",
            "No binary availability is not proof that source cross-compilation is impossible.",
            "16-KB pages, SQLite FTS5 and offline tokenizer assets need Android runtime tests.",
            "ELF load alignment alone does not verify RELRO, APK ZIP alignment or device loading.",
        ],
    }
    (run_dir / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Android Python dependency probe",
        "",
        f"Run ID: `{run_id}`",
        f"Status: `{status}`",
        "",
        "Individual candidates only; a candidate is not an APK or runtime pass.",
        "",
        "| Python | Package | Result |",
        "|---|---|---|",
    ]
    for row in findings:
        lines.append(f"| {row['python']} | {row['package']} | {row['status']} |")
    lines += ["", "## Limits", "", *[f"- {item}" for item in report["limits"]]]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Report: {run_dir / 'report.md'}", flush=True)
    return 0 if status == "candidates_only_runtime_unverified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
