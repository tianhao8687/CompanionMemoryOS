"""Consistent, complete SQLite snapshots; restores are applied before engine startup."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from companion_agent.romance import RomanceSettings
from companion_memoryos.constants import DATABASE_SCHEMA_VERSION
from companion_memoryos.database import Database

MAX_BACKUP_BYTES = 64 * 1024 * 1024
PENDING_NAME = "restore-pending.sqlite"


def validate_snapshot(path: Path) -> None:
    if not 100 <= path.stat().st_size <= MAX_BACKUP_BYTES:
        raise ValueError("备份文件大小无效，当前版本支持最多 64 MB。")
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if not 1 <= version <= DATABASE_SCHEMA_VERSION:
                raise ValueError("此备份的数据版本不受当前应用支持。")
            tables = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {
                "memories",
                "conversation_turns",
                "romance_settings",
                "romance_conversations",
            }.issubset(tables):
                raise ValueError("这不是完整的心隅本地备份。")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ValueError("备份完整性检查未通过。")
            saved = db.execute("SELECT data_json FROM romance_settings WHERE id=1").fetchone()
            if saved is not None:
                try:
                    RomanceSettings.model_validate_json(saved[0])
                except ValidationError:
                    raise ValueError("备份中的应用设置无效，当前数据未更改。") from None
            # Check the columns read immediately after startup, before staging a restore.
            db.execute(
                "SELECT id, title, created_at, updated_at FROM romance_conversations LIMIT 0"
            )
    except sqlite3.DatabaseError:
        raise ValueError("备份文件已损坏或格式不受支持。") from None


def backup_bytes(database: Database) -> bytes:
    # The SQLite backup API includes committed WAL data. Copying the .db alone does not.
    with tempfile.TemporaryDirectory(prefix="snapshot-", dir=database.data_dir) as temp:
        destination = Path(temp) / "backup.sqlite"
        with database.connection() as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target, pages=128)
        validate_snapshot(destination)
        return destination.read_bytes()


def stage_restore(directory: Path, content: bytes) -> None:
    if len(content) > MAX_BACKUP_BYTES:
        raise ValueError("备份文件超过 64 MB。")
    descriptor, filename = tempfile.mkstemp(prefix="restore-", suffix=".sqlite", dir=directory)
    path = Path(filename)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        validate_snapshot(path)
        path.replace(directory / PENDING_NAME)
    finally:
        path.unlink(missing_ok=True)


def apply_pending_restore(directory: Path) -> None:
    """Caller must hold the installation lease and have no application DB connections."""
    pending = directory / PENDING_NAME
    if not pending.exists():
        return
    validate_snapshot(pending)
    target_path = directory / "companion-memoryos.db"
    if target_path.exists():
        recovery = directory / "recovery"
        recovery.mkdir(exist_ok=True)
        prior = recovery / f"before-restore-{uuid4().hex}.sqlite"
        with (
            closing(sqlite3.connect(target_path)) as source,
            closing(sqlite3.connect(prior)) as dest,
        ):
            source.backup(dest)
        validate_snapshot(prior)
    with (
        closing(sqlite3.connect(pending)) as source,
        closing(sqlite3.connect(target_path)) as target,
    ):
        source.backup(target, pages=128)
    pending.unlink()
