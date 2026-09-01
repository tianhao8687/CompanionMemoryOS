from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from companion_memoryos.config import CompanionConfig
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConsentState,
    EmotionSignal,
    EntityRef,
    MemoryInput,
    MemoryKind,
    MemoryStatus,
    RecallRequest,
    RecallUseMode,
    RetrievalOutcome,
    StorageAction,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore


def configured_service(tmp_path: Path, config: CompanionConfig) -> CompanionMemoryService:
    retrieval = config.retrieval.model_copy(
        update={"candidate_pool": 2, "semantic_candidate_pool": 2}
    )
    selected = config.model_copy(update={"retrieval": retrieval})
    database = Database(tmp_path, selected)
    database.initialize()
    return CompanionMemoryService(MemoryStore(database), selected)


def remember(
    service: CompanionMemoryService,
    title: str,
    content: str,
    **extra: object,
) -> str:
    result = service.remember(
        MemoryInput.model_validate(
            {
                "user_id": "alice",
                "kind": MemoryKind.SHARED_MOMENT,
                "title": title,
                "content": content,
                "consent": ConsentState.GRANTED,
                "explicit_user_request": True,
                **extra,
            }
        )
    )
    assert result.memory is not None
    return result.memory.id


def flattened(context: object) -> list[object]:
    from companion_memoryos.schemas import CompanionContext

    assert isinstance(context, CompanionContext)
    return [item for values in context.sections.values() for item in values]


def test_continuous_chinese_text_is_found_outside_recent_pool(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    target_id = remember(service, "雨后的小事", "周六在虹桥公园捡到一只橘色小猫")
    remember(service, "早餐", "早上吃了面包")
    remember(service, "通勤", "下午坐地铁回家")
    remember(service, "工作", "晚上整理了文件")

    context = service.recall(RecallRequest(user_id="alice", query="还记得虹桥公园那只橘猫吗"))

    assert target_id in {item.memory.id for item in flattened(context)}


def test_single_cjk_character_can_reach_candidate(tmp_path: Path, config: CompanionConfig) -> None:
    service = configured_service(tmp_path, config)
    target_id = remember(service, "领养", "家里的猫喜欢睡在窗边")
    remember(service, "晚饭", "今天吃了番茄炒蛋")
    remember(service, "电影", "看了一部老电影")

    context = service.recall(RecallRequest(user_id="alice", query="猫"))

    target = next(item for item in flattened(context) if item.memory.id == target_id)
    assert target.use_mode is RecallUseMode.HEDGE


def test_optional_embedding_finds_a_paraphrase_without_shared_words(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    target_id = remember(
        service,
        "公园救助",
        "在公园照顾过一只受伤的小猫",
        embedding=[1.0, 0.0],
        embedding_space="test-space",
    )
    remember(service, "天气", "今天太阳很好")
    remember(service, "晚餐", "今晚准备煮汤")

    context = service.recall(
        RecallRequest(
            user_id="alice",
            query="那个需要帮助的小动物后来怎么样了",
            query_embedding=[1.0, 0.0],
            embedding_space="test-space",
        )
    )
    items = flattened(context)
    target = next(item for item in items if item.memory.id == target_id)

    assert target.score.semantic == 1.0
    assert target.use_mode is RecallUseMode.NATURAL


def test_entity_id_disambiguates_repeated_keywords(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    wang_id = remember(
        service,
        "咖啡店见面",
        "在蓝岸咖啡店讨论了搬家",
        entities=[EntityRef(id="person:wang", kind="person", name="小王")],
    )
    remember(
        service,
        "咖啡店见面",
        "在蓝岸咖啡店讨论了旅行",
        entities=[EntityRef(id="person:li", kind="person", name="小李")],
    )

    context = service.recall(
        RecallRequest(
            user_id="alice",
            query="咖啡店见面",
            entity_ids=["person:wang"],
        )
    )
    items = flattened(context)

    assert items[0].memory.id == wang_id
    assert items[0].score.entity == 1.0
    assert context.ambiguity_detected is False


def test_last_time_prefers_the_newest_matching_episode(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    remember(
        service,
        "蓝岸咖啡店",
        "第一次在蓝岸咖啡店聊换工作",
        event_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    newest_id = remember(
        service,
        "蓝岸咖啡店",
        "后来在蓝岸咖啡店聊旅行",
        event_at=datetime(2026, 8, 20, tzinfo=UTC),
    )

    context = service.recall(RecallRequest(user_id="alice", query="上次在蓝岸咖啡店聊了什么"))
    items = flattened(context)

    assert items[0].memory.id == newest_id
    assert context.ambiguity_detected is False


def test_explicit_date_filters_the_candidate_pool_before_ranking(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    target_id = remember(
        service,
        "河边散步",
        "在河边散步时捡到一片叶子",
        event_at=datetime(2026, 3, 15, 12, tzinfo=UTC),
    )
    remember(
        service,
        "河边散步",
        "在河边散步时聊了工作",
        event_at=datetime(2026, 5, 15, 12, tzinfo=UTC),
    )
    remember(
        service,
        "河边散步",
        "在河边散步时聊了旅行",
        event_at=datetime(2026, 6, 15, 12, tzinfo=UTC),
    )

    context = service.recall(
        RecallRequest(user_id="alice", query="2026年3月15日河边散步发生了什么")
    )

    assert [item.memory.id for item in flattened(context)] == [target_id]


def test_natural_directive_is_active_without_a_review_modal(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)

    result = service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.BOUNDARY,
            title="称呼边界",
            content="以后不要叫我宝宝",
            consent=ConsentState.GRANTED,
        )
    )

    assert result.action is StorageAction.ACTIVATE
    assert result.memory is not None
    assert result.memory.metadata["natural_directive_detected"] is True


def test_explicit_repeat_promotes_an_existing_candidate_without_a_modal(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    inferred = service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.PREFERENCE,
            title="称呼偏好",
            content="以后叫我小禾",
        )
    )
    assert inferred.memory is not None

    explicit = service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.PREFERENCE,
            title="称呼偏好",
            content="以后叫我小禾",
            consent=ConsentState.GRANTED,
        )
    )

    assert explicit.action is StorageAction.ACTIVATE
    assert explicit.memory is not None
    assert explicit.memory.id != inferred.memory.id
    assert explicit.memory.consent is ConsentState.GRANTED
    assert service.store.get(inferred.memory.id, "alice").status is MemoryStatus.REJECTED
    assert "candidate_replaced_by_direct_evidence" in explicit.reasons


def test_failed_direct_repeat_does_not_destroy_the_existing_candidate(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    inferred = service.remember(
        MemoryInput(
            user_id="alice",
            kind=MemoryKind.PREFERENCE,
            title="称呼偏好",
            content="以后叫我小禾",
        )
    )
    assert inferred.memory is not None

    with pytest.raises(ValueError, match="evidence turns"):
        service.remember(
            MemoryInput(
                user_id="alice",
                kind=MemoryKind.PREFERENCE,
                title="称呼偏好",
                content="以后叫我小禾",
                consent=ConsentState.GRANTED,
                evidence_turn_ids=["missing-turn"],
            )
        )

    assert service.store.get(inferred.memory.id, "alice").status is MemoryStatus.CANDIDATE


def test_unrelated_query_returns_an_explicit_no_match(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    remember(service, "晚饭", "今天吃了番茄炒蛋")

    context = service.recall(RecallRequest(user_id="alice", query="量子计算芯片"))

    assert flattened(context) == []
    assert context.event_fallback == []
    assert context.retrieval_outcome is RetrievalOutcome.NO_MATCH
    assert "不要补写或猜测共同记忆" in context.prompt_text


def test_repeated_keyword_without_person_or_time_cue_is_marked_ambiguous(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    event_at = datetime(2026, 8, 20, tzinfo=UTC)
    remember(service, "蓝岸咖啡店", "在蓝岸咖啡店讨论了搬家", event_at=event_at)
    remember(service, "蓝岸咖啡店", "在蓝岸咖啡店讨论了旅行", event_at=event_at)

    context = service.recall(RecallRequest(user_id="alice", query="蓝岸咖啡店"))

    assert context.ambiguity_detected is True
    assert context.retrieval_outcome is RetrievalOutcome.AMBIGUOUS
    assert context.clarification_guidance is not None


def test_entity_id_can_pull_an_old_memory_into_the_candidate_pool(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    target_id = remember(
        service,
        "毕业典礼",
        "一起拍了毕业合照",
        entities=[EntityRef(id="person:wang", kind="person", name="小王")],
    )
    remember(service, "日常一", "整理了书桌")
    remember(service, "日常二", "买了新的杯子")
    remember(service, "日常三", "晚上看了电影")

    context = service.recall(
        RecallRequest(user_id="alice", query="他那件事", entity_ids=["person:wang"])
    )

    assert target_id in {item.memory.id for item in flattened(context)}


def test_emotion_can_pull_an_old_memory_into_the_candidate_pool(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    anxiety = EmotionSignal(label="焦虑", valence=-0.6, arousal=0.8, intensity=0.8)
    target_id = remember(
        service,
        "演讲之前",
        "先陪我慢慢呼吸，不要马上分析",
        emotions=[anxiety],
    )
    remember(service, "日常一", "整理了书桌")
    remember(service, "日常二", "买了新的杯子")
    remember(service, "日常三", "晚上看了电影")

    context = service.recall(RecallRequest(user_id="alice", emotions=[anxiety]))

    assert target_id in {item.memory.id for item in flattened(context)}


def test_need_can_pull_an_old_memory_into_the_candidate_pool(
    tmp_path: Path,
    config: CompanionConfig,
) -> None:
    service = configured_service(tmp_path, config)
    target_id = remember(
        service,
        "压力很大时",
        "先让我把话完整说完",
        needs=["被倾听"],
    )
    remember(service, "日常一", "整理了书桌")
    remember(service, "日常二", "买了新的杯子")
    remember(service, "日常三", "晚上看了电影")

    context = service.recall(RecallRequest(user_id="alice", needs=["被倾听"]))

    assert target_id in {item.memory.id for item in flattened(context)}
