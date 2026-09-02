"""Small, reversible episode membership operations on the existing SQLite database."""

from __future__ import annotations

import json
import sqlite3
from uuid import uuid4

from companion_memoryos.schemas import (
    ConversationTurnRecord,
    EpisodeAttachRequest,
    EpisodeDetachRequest,
    EpisodeInput,
    EpisodeMergeRequest,
    EpisodeRecord,
    EpisodeSplitRequest,
    EpisodeStatus,
    MemoryScope,
    TurnDeletionState,
)
from companion_memoryos.store import (
    CONSENT_DOMAIN_COLUMNS,
    MemoryStore,
    datetime_to_text,
    scope_from_row,
    scope_values,
    utc_now,
)


class EpisodeStore:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.database = store.database

    def create(self, item: EpisodeInput) -> EpisodeRecord:
        now = utc_now()
        episode_id = str(uuid4())
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO episodes (
                    id, user_id, companion_id, relationship_id, conversation_id, group_id,
                    title, summary, topic_keys_json, participant_actor_ids_json, reality_layer,
                    started_at, last_event_at, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    episode_id,
                    item.user_id,
                    *scope_values(item.scope),
                    item.title,
                    item.summary,
                    json.dumps(item.topic_keys, ensure_ascii=False),
                    json.dumps(item.participant_actor_ids, ensure_ascii=False),
                    item.reality_layer.value,
                    datetime_to_text(item.started_at),
                    datetime_to_text(item.started_at),
                    EpisodeStatus.OPEN.value,
                    datetime_to_text(now),
                    datetime_to_text(now),
                ),
            )
        return self.get(episode_id, item.user_id)

    def get(self, episode_id: str, user_id: str) -> EpisodeRecord:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM episodes WHERE id = ? AND user_id = ?", (episode_id, user_id)
            ).fetchone()
        if row is None:
            raise KeyError(episode_id)
        return self._record(row)

    def list_episodes(self, user_id: str, scope: MemoryScope | None = None) -> list[EpisodeRecord]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM episodes WHERE user_id = ? ORDER BY last_event_at DESC, id",
                (user_id,),
            ).fetchall()
        records = [self._record(row) for row in rows]
        if scope is None:
            return records
        return [record for record in records if self.scope_allows(record.scope, scope)]

    def turns(
        self, episode_id: str, user_id: str, scope: MemoryScope
    ) -> list[ConversationTurnRecord]:
        episode = self.get(episode_id, user_id)
        self._require_scope(episode, scope)
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM conversation_turns WHERE user_id = ? AND episode_id = ? "
                "AND deletion_state = ? ORDER BY occurred_at, server_sequence",
                (user_id, episode_id, TurnDeletionState.ACTIVE.value),
            ).fetchall()
        turns = [self.store._row_to_turn(row) for row in rows]
        return [turn for turn in turns if self.scope_allows(scope, turn.scope)]

    def attach(self, episode_id: str, request: EpisodeAttachRequest) -> EpisodeRecord:
        with self.database.atomic():
            episode = self.get(episode_id, request.user_id)
            self._require_scope(episode, request.scope)
            self._require_revision(episode, request.expected_revision)
            if episode.status is EpisodeStatus.MERGED:
                raise ValueError("cannot attach to a merged episode")
            turn = self.store.get_turn(request.turn_id, request.user_id)
            if not self.scope_allows(request.scope, turn.scope):
                raise ValueError("turn is outside the requested episode scope")
            self._require_scope(episode, turn.scope)
            if turn.deletion_state is not TurnDeletionState.ACTIVE:
                raise ValueError("cannot attach a deleted turn")
            if turn.episode_id == episode_id:
                return episode
            if turn.episode_id != request.expected_episode_id:
                raise ValueError(
                    "episode membership changed; provide expected_episode_id to reassign"
                )
            with self.database.connection() as connection:
                # Do not rewrite content, speech spans or the original ingestion digest.
                connection.execute(
                    "UPDATE conversation_turns SET episode_id = ? WHERE id = ? AND user_id = ?",
                    (episode_id, turn.id, request.user_id),
                )
                self._refresh(connection, episode_id, request.user_id)
                if turn.episode_id is not None:
                    self._refresh(connection, turn.episode_id, request.user_id)
                self.store._audit(
                    connection,
                    episode_id,
                    request.user_id,
                    "episode.turn_reassigned",
                    {"turn_id": turn.id, "previous_episode_id": turn.episode_id},
                    utc_now(),
                )
        return self.get(episode_id, request.user_id)

    def detach(self, episode_id: str, request: EpisodeDetachRequest) -> EpisodeRecord:
        with self.database.atomic() as connection:
            episode = self.get(episode_id, request.user_id)
            self._require_scope(episode, request.scope)
            self._require_revision(episode, request.expected_revision)
            turn = self.store.get_turn(request.turn_id, request.user_id)
            if not self.scope_allows(request.scope, turn.scope) or turn.episode_id != episode_id:
                raise ValueError("turn is not in the requested episode and scope")
            if turn.deletion_state is not TurnDeletionState.ACTIVE:
                raise ValueError("cannot detach a deleted turn")
            connection.execute(
                "UPDATE conversation_turns SET episode_id = NULL WHERE id = ? AND user_id = ?",
                (turn.id, request.user_id),
            )
            self._refresh(connection, episode_id, request.user_id)
            self.store._audit(
                connection,
                episode_id,
                request.user_id,
                "episode.turn_detached",
                {"turn_id": turn.id},
                utc_now(),
            )
        return self.get(episode_id, request.user_id)

    def merge(self, episode_id: str, request: EpisodeMergeRequest) -> EpisodeRecord:
        if episode_id == request.source_episode_id:
            raise ValueError("cannot merge an episode into itself")
        with self.database.atomic() as connection:
            target = self.get(episode_id, request.user_id)
            source = self.get(request.source_episode_id, request.user_id)
            self._require_scope(target, request.scope)
            self._require_scope(source, request.scope)
            self._require_revision(target, request.expected_revision)
            if target.scope != source.scope or target.reality_layer is not source.reality_layer:
                raise ValueError("episode merge requires the same scope and reality layer")
            if EpisodeStatus.MERGED in {target.status, source.status}:
                raise ValueError("cannot merge an already merged episode")
            connection.execute(
                "UPDATE conversation_turns SET episode_id = ? WHERE episode_id = ? AND user_id = ?",
                (episode_id, source.id, request.user_id),
            )
            connection.execute(
                "UPDATE episodes SET status = ?, merged_into_id = ?, summary = '', "
                "revision = revision + 1, updated_at = ? WHERE id = ? AND user_id = ?",
                (
                    EpisodeStatus.MERGED.value,
                    target.id,
                    datetime_to_text(utc_now()),
                    source.id,
                    request.user_id,
                ),
            )
            connection.execute(
                "UPDATE episodes SET topic_keys_json = ?, participant_actor_ids_json = ? "
                "WHERE id = ?",
                (
                    json.dumps(list(dict.fromkeys([*target.topic_keys, *source.topic_keys]))),
                    json.dumps(
                        list(
                            dict.fromkeys(
                                [*target.participant_actor_ids, *source.participant_actor_ids]
                            )
                        )
                    ),
                    target.id,
                ),
            )
            self._refresh(connection, target.id, request.user_id)
            self.store._audit(
                connection,
                target.id,
                request.user_id,
                "episode.merged",
                {"source_id": source.id},
                utc_now(),
            )
        return self.get(episode_id, request.user_id)

    def split(self, episode_id: str, request: EpisodeSplitRequest) -> EpisodeRecord:
        with self.database.atomic():
            original = self.get(episode_id, request.user_id)
            self._require_scope(original, request.scope)
            self._require_revision(original, request.expected_revision)
            if original.status is EpisodeStatus.MERGED:
                raise ValueError("cannot split a merged episode")
            selected = [
                self.store.get_turn(turn_id, request.user_id)
                for turn_id in dict.fromkeys(request.turn_ids)
            ]
            if any(turn.episode_id != episode_id for turn in selected):
                raise ValueError("split turns must all belong to the source episode")
            created = self.create(
                EpisodeInput(
                    user_id=request.user_id,
                    scope=original.scope,
                    title=request.title,
                    topic_keys=original.topic_keys,
                    participant_actor_ids=original.participant_actor_ids,
                    reality_layer=original.reality_layer,
                    started_at=min(turn.occurred_at for turn in selected),
                )
            )
            for turn in selected:
                self.attach(
                    created.id,
                    EpisodeAttachRequest(
                        user_id=request.user_id,
                        scope=request.scope,
                        turn_id=turn.id,
                        expected_episode_id=episode_id,
                    ),
                )
        return self.get(created.id, request.user_id)

    @staticmethod
    def scope_allows(container: MemoryScope, member: MemoryScope) -> bool:
        return all(
            getattr(container, name) == getattr(member, name) for name in CONSENT_DOMAIN_COLUMNS
        ) and (
            container.conversation_id is None or container.conversation_id == member.conversation_id
        )

    @classmethod
    def _require_scope(cls, episode: EpisodeRecord, scope: MemoryScope) -> None:
        if not cls.scope_allows(episode.scope, scope):
            raise ValueError("episode is outside the requested scope")

    @staticmethod
    def _require_revision(episode: EpisodeRecord, expected: int | None) -> None:
        if expected is not None and episode.revision != expected:
            raise ValueError("episode revision changed")

    @staticmethod
    def _refresh(connection: sqlite3.Connection, episode_id: str, user_id: str) -> None:
        interval = connection.execute(
            "SELECT MIN(occurred_at) AS first, MAX(occurred_at) AS last FROM conversation_turns "
            "WHERE episode_id = ? AND user_id = ? AND deletion_state = ?",
            (episode_id, user_id, TurnDeletionState.ACTIVE.value),
        ).fetchone()
        connection.execute(
            "UPDATE episodes SET started_at = COALESCE(?, started_at), "
            "last_event_at = COALESCE(?, last_event_at), summary = '', "
            "status = CASE WHEN ? IS NULL THEN 'empty' "
            "WHEN status = 'empty' THEN 'open' ELSE status END, "
            "revision = revision + 1, updated_at = ? WHERE id = ? AND user_id = ?",
            (
                interval["first"],
                interval["last"],
                interval["first"],
                datetime_to_text(utc_now()),
                episode_id,
                user_id,
            ),
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> EpisodeRecord:
        return EpisodeRecord(
            id=row["id"],
            user_id=row["user_id"],
            scope=scope_from_row(row),
            title=row["title"],
            summary=row["summary"],
            topic_keys=json.loads(row["topic_keys_json"]),
            participant_actor_ids=json.loads(row["participant_actor_ids_json"]),
            reality_layer=row["reality_layer"],
            started_at=row["started_at"],
            last_event_at=row["last_event_at"],
            status=row["status"],
            merged_into_id=row["merged_into_id"],
            revision=row["revision"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
