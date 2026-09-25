"""Acceptance of the frozen Windows engine using only fresh synthetic data."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    engine = args.engine.resolve(strict=True)
    run_id = "native-bundle-" + uuid4().hex
    run = root / ".agent-tests" / run_id
    run.mkdir(parents=True)
    env = dict(os.environ, XINYU_TEST_ENGINE=str(engine))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_local_runtime.py",
            "-q",
            "--basetemp",
            str(run / "synthetic"),
            "--junitxml",
            str(run / "junit.xml"),
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    (run / "test-output.txt").write_text(result.stdout + result.stderr, encoding="utf-8")
    evidence = {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "passed" if result.returncode == 0 else "failed",
        "kind": "frozen_windows_engine",
        "model_calls": 0,
        "gui_test": "not_run",
        "engine_sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
        "exit_code": result.returncode,
    }
    (run / "results.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    if result.returncode:
        print(result.stdout[-5000:])
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
