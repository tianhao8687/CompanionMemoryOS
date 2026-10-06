"""Bounded, literal search over the live conversation ledger (no duplicate index)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

if TYPE_CHECKING:
    from companion_agent.app import RomanceHost


def excerpt(content: str, query: str) -> str:
    start = max(0, content.lower().find(query.lower()) - 35)
    end = min(len(content), start + 180)
    return ("…" if start else "") + content[start:end] + ("…" if end < len(content) else "")


def _rows(host: RomanceHost, clause: str, parameters: list[Any], limit: int) -> list[Any]:
    with host.database.connection() as db:
        return list(
            db.execute(
                "SELECT t.*, c.title AS conversation_title FROM conversation_turns t "
                "JOIN romance_conversations c ON c.id=t.conversation_id "
                "WHERE t.user_id=? AND t.companion_id=? AND t.relationship_id=? "
                "AND t.group_id IS NULL AND t.deletion_state='active' AND t.consent='granted' "
                "AND t.role IN ('user','assistant') AND " + clause + " LIMIT ?",
                [
                    host.key.user_id,
                    host.key.companion_id,
                    host.key.relationship_id,
                    *parameters,
                    limit,
                ],
            ).fetchall()
        )


def search(
    host: RomanceHost, query: str, conversation: str | None, before: int | None, limit: int
) -> dict[str, Any]:
    query = query.strip()
    if not query:
        return {"results": [], "has_more": False, "before": None}
    if conversation:
        host.scope(conversation)
    rows = _rows(
        host,
        "instr(lower(t.content),lower(?))>0 "
        "AND (? IS NULL OR t.conversation_id=?) "
        "AND (? IS NULL OR t.server_sequence<?) ORDER BY t.server_sequence DESC",
        [query, conversation, conversation, before, before],
        limit + 1,
    )
    return {
        "results": [
            {
                "message": host.public_turn(host.memory.store._row_to_turn(row)),
                "conversation_id": row["conversation_id"],
                "title": row["conversation_title"],
                "excerpt": excerpt(row["content"], query),
            }
            for row in rows[:limit]
        ],
        "has_more": len(rows) > limit,
        "before": rows[min(limit, len(rows)) - 1]["server_sequence"] if rows else None,
    }


def context(host: RomanceHost, conversation: str, identifier: str) -> dict[str, Any]:
    host.scope(conversation)
    anchor = _rows(host, "t.id=? AND t.conversation_id=?", [identifier, conversation], 1)
    if not anchor:
        raise HTTPException(404, detail={"message": "这条记录已不可用，请重新搜索。"})
    sequence = anchor[0]["server_sequence"]
    older = _rows(
        host,
        "t.conversation_id=? AND t.server_sequence<? ORDER BY t.server_sequence DESC",
        [conversation, sequence],
        12,
    )
    newer = _rows(
        host,
        "t.conversation_id=? AND t.server_sequence>? ORDER BY t.server_sequence ASC",
        [conversation, sequence],
        12,
    )
    return {
        "messages": [
            host.public_turn(host.memory.store._row_to_turn(row))
            for row in [*reversed(older), *anchor, *newer]
        ],
        "anchor": identifier,
    }
