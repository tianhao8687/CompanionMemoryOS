from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from companion_memoryos.database import Database


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class AutomationStore:
    def __init__(self, database: Database) -> None:
        self.database = database
        with database.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_config (
                    id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_actions (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, request_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL, arguments TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_jobs (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL, next_run TEXT NOT NULL,
                    status TEXT NOT NULL, last_result TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS agent_notifications (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, title TEXT NOT NULL,
                    message TEXT NOT NULL, created_at TEXT NOT NULL,
                    seen INTEGER NOT NULL DEFAULT 0);
            """)

    def recover(self) -> None:
        # A crash after an external effect cannot safely be retried automatically.
        with self.database.connection() as db:
            db.execute(
                "UPDATE agent_actions SET status='uncertain', result=?, updated_at=? "
                "WHERE status='running'",
                (
                    json.dumps({"status": "uncertain", "message": "执行中断，请先核对外部结果。"}),
                    utc_now(),
                ),
            )
            db.execute(
                "UPDATE agent_jobs SET status='paused', last_result=? WHERE status='running'",
                ("服务执行时中断，已暂停；请核对结果后恢复。",),
            )

    def actions(self, conversation_id: str | None = None) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            if conversation_id is None:
                rows = db.execute(
                    "SELECT * FROM agent_actions ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT * FROM agent_actions WHERE conversation_id=? "
                    "ORDER BY created_at DESC LIMIT 20",
                    (conversation_id,),
                ).fetchall()
        return [self.action_dict(dict(row)) for row in rows]

    @staticmethod
    def action_dict(row: dict[str, Any]) -> dict[str, Any]:
        row["arguments"] = json.loads(row["arguments"])
        row["result"] = json.loads(row["result"])
        row.pop("fingerprint", None)
        return row

    def notification(self, conversation: str, title: str, message: str) -> None:
        with self.database.connection() as db:
            db.execute(
                "INSERT INTO agent_notifications VALUES (?, ?, ?, ?, ?, 0)",
                (str(uuid4()), conversation, title[:100], message[:4000], utc_now()),
            )

    def notifications(self) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM agent_notifications ORDER BY created_at DESC LIMIT 100"
                ).fetchall()
            ]

    def jobs(self) -> list[dict[str, Any]]:
        with self.database.connection() as db:
            rows = db.execute("SELECT * FROM agent_jobs ORDER BY created_at DESC LIMIT 200")
            return [{**dict(row), "data": json.loads(row["data"])} for row in rows]
