"""Listening provenance and lifecycle through ordinary chat, with synthetic media."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from companion_agent.cognition import CognitionSettings
from companion_agent.music_memory import listening_share
from companion_memoryos.schemas import (
    ExperienceEvidenceKind,
    MemoryKind,
    MemoryReferenceFeedbackInput,
    MemoryStatus,
    ReferenceFeedbackKind,
)
from tests.test_automatic_memory import visible_context
from tests.test_companion_functional import chat, host_for
from tests.test_music import listening as listening_fixture
from tests.test_music import poll

listening = listening_fixture

SHARE = "毕业那天我一直听这首歌，想起了我们一起搬桌子的下午。"


def moments(f: Any) -> list[Any]:
    return [
        record
        for record in f.host.memory.store.list_memories(f.host.key.user_id, {MemoryStatus.ACTIVE})
        if record.metadata.get("shared_listening")
    ]


def send(f: Any, text: str = SHARE, key: str = "share", conversation: str | None = None):
    return chat(f.host, text, key, conversation or f.item["conversation_id"])


def test_share_keeps_player_and_user_evidence_separate_and_recalls_after_restart(
    listening: Any, tmp_path: Path
) -> None:
    f = listening
    sent = send(f)
    record = moments(f)[0]
    assert record.kind is MemoryKind.SHARED_MOMENT
    assert record.content == SHARE
    assert record.evidence_turn_ids == [sent["user"]["id"]]
    assert record.scope.conversation_id is None
    observed = record.metadata["shared_listening"]
    assert observed["title"] == "合成歌曲" and observed["artist"] == "测试歌手"
    assert observed["source"] == "netease_player_metadata"
    assert record.salience < 1  # Listening does not automatically become the most important memory.
    send(f)  # Same request and source must not create another moment or change its song.
    assert len(moments(f)) == 1
    f.host.memory.close_indexer()
    restarted = host_for(tmp_path, f.model, cognition=CognitionSettings(embedding_backend="off"))
    try:
        chat(restarted, "合成歌曲让我想起什么？", "recall", restarted.new_conversation()["id"])
        context = visible_context(f.model)
        assert SHARE in context and "user_share_during_app_listening" in context
        assert "netease_player_metadata" in context
        assert "歌词引用不等于用户经历" in context
    finally:
        restarted.memory.close_indexer()


@pytest.mark.parametrize(
    "text",
    [
        "我喜欢这首歌。",
        "这首歌让我想起以前住的小院子。",
        "这首歌不好听，我不喜欢这个版本。",
        "记住这首歌，它陪我熬过了第一次搬家的晚上。",
    ],
)
def test_explicit_shares_bind_deictic_song_without_unresolved_profile(
    listening: Any, text: str
) -> None:
    f = listening
    send(f, text)
    assert len(moments(f)) == 1
    assert not any(
        item.kind is MemoryKind.PREFERENCE and "这首" in item.content
        for item in f.host.memory.store.list_memories(f.host.key.user_id, {MemoryStatus.ACTIVE})
    )


@pytest.mark.parametrize(
    "text",
    [
        "帮我找并播放这首歌。",
        "这首歌叫什么？",
        "你喜欢这首歌吗？",
        "如果我喜欢这首歌，我们就一起听。",
        "她说：我喜欢这首歌。",
        "歌词是“这首歌让我想起我们相识的晚上”。",
        "我今天买了个水杯。",
        "这首歌让我想起毕业，但不要记录这个。",
        "我喜欢这首歌，但不要记录这个。",
        "这首歌让我想到药物和诊断。",
    ],
)
def test_requests_quotes_uncertainty_and_unrelated_chat_do_not_create_moments(
    listening: Any, text: str
) -> None:
    send(listening, text)
    assert not moments(listening)
    assert not any(
        item.kind is MemoryKind.PREFERENCE and "这首" in item.content
        for item in listening.host.memory.store.list_memories(
            listening.host.key.user_id, {MemoryStatus.ACTIVE}
        )
    )


@pytest.mark.parametrize("state", ["paused", "missing", "stale", "ended", "disabled", "off"])
def test_no_association_without_fresh_authorized_playback(listening: Any, state: str) -> None:
    f = listening
    if state == "paused":
        f.bridge.state["playback"] = "paused"
        f.now[0] += 2
        poll(f)
    elif state == "missing":
        f.bridge.state["available"] = False
        f.now[0] += 2
        poll(f)
    elif state == "stale":
        f.now[0] += 6
    elif state == "ended":
        f.client.post("/api/music", json={**f.item, "action": "end"})
    elif state == "disabled":
        f.host.memory.learning.extract_memory = False
    else:
        f.host.tools.config.servers[0].enabled = False
    send(f)
    assert not moments(f)


def test_another_conversation_cannot_inherit_live_song_and_polling_creates_no_memory(
    listening: Any,
) -> None:
    f = listening
    for _ in range(3):
        f.now[0] += 2
        poll(f)
    assert not moments(f)
    send(f, conversation=f.host.new_conversation()["id"])
    assert not moments(f)


def test_same_song_reference_retrieves_existing_moment_in_a_new_listening_session(
    listening: Any,
) -> None:
    f = listening
    send(f)
    other = f.host.new_conversation()["id"]
    f.client.post("/api/music", json={"action": "start", "conversation_id": other})
    send(f, "还记得这首歌让我想起什么吗？", "again", other)
    assert SHARE in visible_context(f.model)
    assert "user_share_during_app_listening" in visible_context(f.model)
    assert len(moments(f)) == 1


@pytest.mark.parametrize("operation", ["forget_song", "delete_source", "restrict_source"])
def test_shared_memory_obeys_forgetting_deletion_and_source_restrictions(
    listening: Any, operation: str
) -> None:
    f = listening
    sent = send(f)
    record = moments(f)[0]
    if operation == "forget_song":
        send(f, "请忘记合成歌曲的事", "forget")
    elif operation == "delete_source":
        f.host.memory.forget_turn(sent["user"]["id"], f.host.key.user_id)
    else:
        f.host.memory.record_reference_feedback(
            MemoryReferenceFeedbackInput(
                user_id=f.host.key.user_id,
                scope=f.host.scope(f.item["conversation_id"]),
                evidence_kind=ExperienceEvidenceKind.TURN,
                evidence_id=sent["user"]["id"],
                kind=ReferenceFeedbackKind.DO_NOT_REFERENCE,
            )
        )
    send(f, "合成歌曲让我想起什么？", "recall", f.host.new_conversation()["id"])
    context = visible_context(f.model)
    assert SHARE not in context and record.id not in context
    assert "user_share_during_app_listening" not in context


def test_explicit_correction_versions_the_same_moment_and_hides_old_statement(
    listening: Any,
) -> None:
    f = listening
    send(f)
    first = moments(f)[0]
    corrected = "刚才说错了，这首歌让我想起的是入学时合唱的下午。"
    sent = send(f, corrected, "correction")
    current = moments(f)
    assert len(current) == 1 and current[0].stable_key == first.stable_key
    assert current[0].content == corrected
    assert current[0].evidence_turn_ids == [sent["user"]["id"]]
    assert f.host.memory.store.get(first.id, f.host.key.user_id).status is MemoryStatus.SUPERSEDED
    send(f, "合成歌曲让我想起什么？", "recall", f.host.new_conversation()["id"])
    context = visible_context(f.model)
    assert corrected in context and SHARE not in context


def test_existing_memory_editor_can_correct_a_listening_moment(listening: Any) -> None:
    f = listening
    send(f)
    record = moments(f)[0]
    corrected = "其实是在入学那天听这首歌。"
    response = f.client.put(
        f"/api/memories/{record.id}",
        json={"content": corrected, "conversation_id": f.item["conversation_id"]},
    )
    assert response.status_code == 200, response.text
    assert moments(f)[0].content == corrected


def test_repeated_request_does_not_rebind_a_past_share_to_a_changed_track(listening: Any) -> None:
    f = listening
    send(f)
    observed = moments(f)[0].metadata["shared_listening"]
    f.bridge.state["title"] = "另一首合成曲"
    f.now[0] += 2
    poll(f)
    send(f)
    assert len(moments(f)) == 1
    assert moments(f)[0].metadata["shared_listening"] == observed


def test_quote_is_preserved_as_a_quote_beside_an_explicit_personal_share(listening: Any) -> None:
    text = "歌词是“我住在云上”。这首歌让我想起搬家那天。"
    send(listening, text)
    record = moments(listening)[0]
    assert record.content == text and record.metadata["quoted_material_reference"]
    assert not listening.host.memory.profile(listening.host.key.user_id).identity


def test_song_title_that_is_common_speech_is_not_enough_to_infer_music_share() -> None:
    assert not listening_share("我爱你", "我爱你")
    assert not listening_share("我喜欢这个版本的你", "合成歌曲")
    assert not listening_share("我喜欢这首诗", "合成歌曲")
