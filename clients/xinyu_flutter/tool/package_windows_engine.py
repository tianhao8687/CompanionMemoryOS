"""Build a relocatable Python runtime with no Python installation required by users."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from prepare_engine import prepare


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    source = prepare(args.work / "source")
    args.output.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "xinyu-engine",
        "--distpath",
        str(args.output),
        "--workpath",
        str(args.work / "pyinstaller"),
        "--specpath",
        str(args.work),
        "--paths",
        str(source),
        "--collect-data",
        "companion_agent",
        "--collect-data",
        "companion_memoryos",
        "--collect-submodules",
        "tiktoken_ext",
        "--hidden-import",
        "uvicorn.logging",
        "--hidden-import",
        "uvicorn.loops.asyncio",
        "--hidden-import",
        "uvicorn.protocols.http.h11_impl",
        "--hidden-import",
        "uvicorn.lifespan.on",
        "--hidden-import",
        "tzdata",
        "--collect-data",
        "tzdata",
        "--copy-metadata",
        "jsonschema",
        "--add-data",
        f"{source / 'companion_agent' / 'assets'};companion_agent/assets",
        str(Path(__file__).with_name("engine_entry.py")),
    ]
    subprocess.run(command, check=True)
    print(
        json.dumps(
            {
                "engine": str(args.output / "xinyu-engine" / "xinyu-engine.exe"),
                "manifest": str(args.work / "source" / "engine-manifest.json"),
            }
        )
    )


if __name__ == "__main__":
    main()
