from __future__ import annotations

import json

from companion_agent.experience.models import CompiledExperienceContext, ExperienceRecallItem
from companion_agent.relationship.models import RelationshipKey
from companion_memoryos.tokens import TokenCounter


def compile_experience_context(
    key: RelationshipKey,
    items: list[ExperienceRecallItem],
    token_counter: TokenCounter,
    *,
    max_tokens: int = 800,
) -> CompiledExperienceContext:
    selected: list[dict[str, object]] = []
    ids = []
    covered: set[str] = set()
    for item in items:
        record = item.experience
        if record.key != key:
            raise ValueError("cross-owner experience context")
        payload = {
            "experience_id": record.experience_id,
            "revision": record.revision,
            "type": record.type.value,
            "source": "lived",
            "participants": record.participants,
            "title": record.title,
            "summary": record.summary,
            "status": record.status.value,
            "started_at": record.started_at.isoformat(),
            "ended_at": record.ended_at.isoformat() if record.ended_at else None,
            "use_mode": item.use_mode.value,
            "evidence_count": len(record.facts),
        }
        trial = json.dumps([*selected, payload], ensure_ascii=False, separators=(",", ":"))
        if token_counter.count(trial) <= max_tokens:
            selected.append(payload)
            ids.append(record.experience_id)
            covered.update(fact.evidence_ref.key for fact in record.facts)
    text = json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
    if max_tokens < token_counter.count(text):
        raise ValueError("experience budget cannot fit empty context")
    return CompiledExperienceContext(
        **key.model_dump(),
        text=text,
        estimated_tokens=token_counter.count(text),
        experience_ids=ids,
        omitted_count=len(items) - len(ids),
        covered_evidence_ids=sorted(covered),
    )
