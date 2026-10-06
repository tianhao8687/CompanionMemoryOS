"""Fetch the pinned SQLite amalgamation for the Android FTS5-enabled library."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import urllib.request
from pathlib import Path
from zipfile import ZipFile

URL = "https://www.sqlite.org/2025/sqlite-amalgamation-3500400.zip"
SHA256 = "1d3049dd0f830a025a53105fc79fd2ab9431aea99e137809d064d8ee8356b032"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Output directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=90) as response:
        content = response.read()
    (output / "source.zip").write_bytes(content)
    if hashlib.sha256(content).hexdigest() != SHA256:
        raise RuntimeError("SQLite source checksum mismatch; download retained for inspection")
    with ZipFile(io.BytesIO(content)) as archive:
        for name in ("sqlite3.c", "sqlite3.h", "sqlite3ext.h"):
            (output / name).write_bytes(archive.read("sqlite-amalgamation-3500400/" + name))
    (output / "source-receipt.json").write_text(
        json.dumps({"version": "3.50.4", "url": URL, "sha256": SHA256}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Verified SQLite 3.50.4 source: {output / 'sqlite3.c'}")


if __name__ == "__main__":
    main()
