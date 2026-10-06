"""Stage the original engine and exact tokenizer assets for native packaging."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path


def prepare(output: Path) -> Path:
    repository = Path(__file__).resolve().parents[3]
    output = output.resolve()
    # A fresh staging directory prevents deleted source modules surviving a rebuild.
    if output.exists() and any(output.iterdir()):
        raise ValueError("Engine staging directory must be new or empty")
    output.mkdir(parents=True, exist_ok=True)
    python = output / "python"
    for package in ("companion_agent", "companion_memoryos"):
        shutil.copytree(
            repository / package,
            python / package,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    assets = python / "companion_agent" / "assets" / "tokenizers"
    assets.mkdir(parents=True)
    # This is a build-time download of public tokenizer data, not a model call.
    os.environ["TIKTOKEN_CACHE_DIR"] = str(assets)
    import tiktoken

    from companion_memoryos.config import load_config

    encoding = load_config().tokenization.encoding
    tiktoken.get_encoding(encoding)
    if not any(assets.iterdir()):
        raise RuntimeError("Tokenizer assets missing; an offline installation must not fetch them")
    shutil.copy2(repository / "LICENSE", output / "LICENSE")
    manifest = {
        "tokenizer": encoding,
        "files": {
            path.relative_to(python).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(python.rglob("*"))
            if path.is_file()
        },
    }
    (output / "engine-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return python


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.output))


if __name__ == "__main__":
    main()
