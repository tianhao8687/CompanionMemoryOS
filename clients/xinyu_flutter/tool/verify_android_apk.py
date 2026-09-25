"""Check Python's Java bridge in the final, R8-optimized APK, not build inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path
from zipfile import ZipFile

BRIDGE = "Lcom/xinyu/xinyu_flutter/DeviceCredentials;"
REQUIRED_METHODS = {
    "<init>(Landroid/content/Context;)V",
    "load(Ljava/lang/String;)Ljava/lang/String;",
    "save(Ljava/lang/String;Ljava/lang/String;)V",
    "delete(Ljava/lang/String;)V",
}


def bridge_methods(data: bytes) -> set[str] | None:
    if not data.startswith(b"dex\n"):
        raise ValueError("Unsupported DEX file")

    def uleb(offset: int) -> tuple[int, int]:
        value, shift = 0, 0
        while shift < 35:
            byte = data[offset]
            offset += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value, offset
            shift += 7
        raise ValueError("Invalid DEX integer")

    def table(header: int) -> tuple[int, int]:
        return struct.unpack_from("<II", data, header)

    strings = []
    count, offset = table(56)
    for index in range(count):
        start = struct.unpack_from("<I", data, offset + index * 4)[0]
        _, start = uleb(start)
        # Only ASCII descriptors and method names are compared below.
        strings.append(data[start : data.index(b"\0", start)].decode("utf-8", "replace"))
    count, offset = table(64)
    types = [strings[struct.unpack_from("<I", data, offset + i * 4)[0]] for i in range(count)]
    count, offset = table(72)
    prototypes = []
    for index in range(count):
        _, result, parameters = struct.unpack_from("<III", data, offset + index * 12)
        arguments = ""
        if parameters:
            size = struct.unpack_from("<I", data, parameters)[0]
            arguments = "".join(
                types[struct.unpack_from("<H", data, parameters + 4 + i * 2)[0]]
                for i in range(size)
            )
        prototypes.append(f"({arguments}){types[result]}")
    count, offset = table(88)
    methods = []
    for index in range(count):
        owner, prototype, name = struct.unpack_from("<HHI", data, offset + index * 8)
        methods.append((types[owner], strings[name] + prototypes[prototype]))
    count, offset = table(96)
    for index in range(count):
        owner = struct.unpack_from("<I", data, offset + index * 32)[0]
        if types[owner] != BRIDGE:
            continue
        position = struct.unpack_from("<I", data, offset + index * 32 + 24)[0]
        if not position:
            return set()
        sizes = []
        for _ in range(4):
            size, position = uleb(position)
            sizes.append(size)
        for _ in range(sizes[0] + sizes[1]):
            _, position = uleb(position)
            _, position = uleb(position)
        found = set()
        for size in sizes[2:]:
            method_index = 0
            for _ in range(size):
                difference, position = uleb(position)
                access, position = uleb(position)
                code, position = uleb(position)
                method_index += difference
                method_owner, signature = methods[method_index]
                if method_owner == BRIDGE and access & 1 and code:
                    found.add(signature)
        return found
    return None


def inspect_apk(apk: Path) -> dict[str, object]:
    found: set[str] | None = None
    with ZipFile(apk) as archive:
        for name in archive.namelist():
            if name.endswith(".dex"):
                found = bridge_methods(archive.read(name))
                if found is not None:
                    break
    with apk.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    missing = sorted(REQUIRED_METHODS - (found or set()))
    return {
        "apk_sha256": digest,
        "bridge_present": found is not None,
        "public_bridge_methods": sorted(found or set()),
        "missing_methods": missing,
        "status": "passed" if found is not None and not missing else "failed",
        "android_runtime": "not_run",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = inspect_apk(args.apk)
    serialized = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
