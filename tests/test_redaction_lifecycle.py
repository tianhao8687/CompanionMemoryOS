"""Full redactions must leave neither active replies nor legacy sources behind."""

from pathlib import Path

from companion_agent.app import LOCAL_USER
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    TurnDeletionState,
)
from tests.test_companion_functional import chat, host_for
from tests.test_romance_app import RecordingLLM


def test_restart_repairs_legacy_empty_redactions_once_and_preserves_other_messages(
    tmp_path: Path,
) -> None:
    model = RecordingLLM()
    host = host_for(tmp_path, model)
    original = chat(host, "备用门卡放在玄关藤篮最下层。", "source")
    independent = chat(host, "帮我给相册写一句文案。", "draft")
    partial = chat(host, "旧胶片盒放在橙色帆布袋里，里面有一卷冲坏的黑白胶片。", "partial")
    partial_turn = host.memory.store.get_turn(partial["user"]["id"], LOCAL_USER)
    kept = host.memory.store.redact_turn(
        partial_turn.id, LOCAL_USER, [(0, partial_turn.content.index("，") + 1)]
    )
    # Emulate a pre-fix database: the source is empty, but it and its reply remain active.
    with host.database.connection() as db:
        db.execute(
            "UPDATE conversation_turns SET content='[已遗忘指定位置]', "
            "metadata_json='{\"content_redacted_empty\":true}' WHERE id=?",
            (original["user"]["id"],),
        )
    first_redaction_time = None
    for _ in range(2):
        restarted = host_for(tmp_path, model)
        for role in ("user", "assistant"):
            turn = restarted.memory.store.get_turn(original[role]["id"], LOCAL_USER)
            assert turn.deletion_state is TurnDeletionState.FORGOTTEN
            assert turn.content == "[已遗忘指定位置]"
        if first_redaction_time is None:
            first_redaction_time = turn.metadata["content_redacted_at"]
        else:
            assert turn.metadata["content_redacted_at"] == first_redaction_time
        for role in ("user", "assistant"):
            turn = restarted.memory.store.get_turn(independent[role]["id"], LOCAL_USER)
            assert turn.deletion_state is TurnDeletionState.ACTIVE
        partial_after = restarted.memory.store.get_turn(kept.id, LOCAL_USER)
        assert partial_after.deletion_state is TurnDeletionState.ACTIVE
        assert partial_after.content == kept.content == "里面有一卷冲坏的黑白胶片。"


def test_legacy_redaction_repair_is_scoped_to_its_user(service) -> None:
    sources = {}
    for user_id in ("owner", "other"):
        sources[user_id] = service.append_turn(
            ConversationTurnInput(
                user_id=user_id,
                scope={"conversation_id": "shared-label"},
                actor_id=user_id,
                role=ConversationRole.USER,
                content="[已遗忘指定位置]",
                consent=ConsentState.GRANTED,
                metadata={"content_redacted_empty": True},
            )
        ).turn
    service.store.repair_empty_redactions("owner")
    assert (
        service.store.get_turn(sources["owner"].id, "owner").deletion_state
        is TurnDeletionState.FORGOTTEN
    )
    assert (
        service.store.get_turn(sources["other"].id, "other").deletion_state
        is TurnDeletionState.ACTIVE
    )
