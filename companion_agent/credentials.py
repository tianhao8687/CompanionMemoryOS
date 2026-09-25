"""Opt-in API credentials in the current Windows user's credential manager."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any


class CredentialStoreError(RuntimeError):
    """A credential operation failed; never include credential contents in errors."""


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class CredentialStore:
    def __init__(self, data_dir: Path, *, enabled: bool = True) -> None:
        self.available = enabled and os.name == "nt"
        self.scope = os.path.normcase(str(data_dir.resolve()))

    def target(self, endpoint: str) -> str:
        # Separate installations and providers cannot silently inherit each other's key.
        identity = json.dumps([self.scope, endpoint.rstrip("/")], ensure_ascii=False)
        return "CompanionMemoryOS/romance/" + hashlib.sha256(identity.encode()).hexdigest()

    def _library(self) -> Any:
        if not self.available:
            raise CredentialStoreError("credential_store_unavailable")
        library = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        library.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_Credential)),
        ]
        library.CredReadW.restype = wintypes.BOOL
        library.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
        library.CredWriteW.restype = wintypes.BOOL
        library.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        library.CredDeleteW.restype = wintypes.BOOL
        library.CredFree.argtypes = [ctypes.c_void_p]
        library.CredFree.restype = None
        return library

    def load(self, endpoint: str) -> str | None:
        if not self.available:
            return None
        library = self._library()
        credential = ctypes.POINTER(_Credential)()
        if not library.CredReadW(self.target(endpoint), 1, 0, ctypes.byref(credential)):
            if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
                return None
            raise CredentialStoreError("credential_store_read_failed")
        try:
            record = credential.contents
            if not 0 < record.CredentialBlobSize <= 512 or not record.CredentialBlob:
                raise CredentialStoreError("credential_store_invalid_value")
            value = ctypes.string_at(record.CredentialBlob, record.CredentialBlobSize)
            if not value.isascii() or any(byte <= 32 or byte >= 127 for byte in value):
                raise CredentialStoreError("credential_store_invalid_value")
            return value.decode("ascii")
        finally:
            library.CredFree(credential)

    def save(self, endpoint: str, value: str) -> None:
        if (
            not 0 < len(value) <= 512
            or not value.isascii()
            or not value.isprintable()
            or any(character.isspace() for character in value)
        ):
            raise CredentialStoreError("credential_store_invalid_value")
        library = self._library()
        blob = ctypes.create_string_buffer(value.encode("ascii"))
        credential = _Credential(
            Type=1,  # CRED_TYPE_GENERIC
            TargetName=self.target(endpoint),
            Comment="CompanionMemoryOS API key for this installation and provider",
            CredentialBlobSize=len(value),
            CredentialBlob=ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte)),
            Persist=2,  # CRED_PERSIST_LOCAL_MACHINE: this user, this computer
            UserName="CompanionMemoryOS",
        )
        try:
            if not library.CredWriteW(ctypes.byref(credential), 0):
                raise CredentialStoreError("credential_store_write_failed")
        finally:
            ctypes.memset(blob, 0, ctypes.sizeof(blob))

    def delete(self, endpoint: str) -> None:
        library = self._library()
        if not library.CredDeleteW(self.target(endpoint), 1, 0) and ctypes.get_last_error() != 1168:
            raise CredentialStoreError("credential_store_delete_failed")
