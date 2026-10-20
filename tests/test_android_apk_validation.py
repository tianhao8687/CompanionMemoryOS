"""A ZIP-aligned APK can still contain native libraries unusable on 16 KB devices."""

import importlib.util
import struct
from pathlib import Path

import pytest

CHECKER = Path(__file__).resolve().parents[1] / "clients/xinyu_flutter/tool/verify_android_apk.py"
spec = importlib.util.spec_from_file_location("android_apk_validation", CHECKER)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def elf(*alignments: int, machine: int = 183, virtual_offset: int = 0) -> bytes:
    data = bytearray(64 + len(alignments) * 56)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<H", data, 18, machine)
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, len(alignments))
    for index, alignment in enumerate(alignments):
        start = 64 + index * 56
        struct.pack_into("<I", data, start, 1)
        struct.pack_into("<QQ", data, start + 8, 0, virtual_offset)
        struct.pack_into("<Q", data, start + 48, alignment)
    return bytes(data)


@pytest.mark.parametrize("alignment", [16384, 65536])
def test_supports_16kb_and_larger_load_segments(alignment: int) -> None:
    assert checker.arm64_16kb_compatible(elf(alignment, alignment))


@pytest.mark.parametrize(
    "data",
    [
        elf(16384, 4096),
        elf(16384, virtual_offset=4096),
        elf(24576),
        elf(16384, machine=62),
        elf(),
        elf(16384)[:-1],
        b"not an ELF",
    ],
)
def test_rejects_incompatible_or_malformed_native_library(data: bytes) -> None:
    assert not checker.arm64_16kb_compatible(data)
