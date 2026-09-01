from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from companion_memoryos.config import CompanionConfig, load_config


def test_fingerprint_is_stable() -> None:
    assert load_config().fingerprint() == load_config().fingerprint()


def test_partial_override_keeps_unmentioned_defaults(tmp_path: Path) -> None:
    override = tmp_path / "override.toml"
    override.write_text("[retrieval]\ndefault_limit = 5\n", encoding="utf-8")
    config = load_config(override)
    assert config.retrieval.default_limit == 5
    assert config.retrieval.max_limit == 25


def test_non_loopback_server_is_rejected() -> None:
    data = load_config().model_dump(mode="python")
    data["server"]["host"] = "0.0.0.0"
    with pytest.raises(ValidationError, match="loopback"):
        CompanionConfig.model_validate(data)


def test_ranking_weights_must_sum_to_one() -> None:
    data = load_config().model_dump(mode="python")
    data["ranking"]["lexical"] = 0.99
    with pytest.raises(ValidationError, match=r"sum to 1\.0"):
        CompanionConfig.model_validate(data)


def test_prototype_policy_bundle_cannot_be_marked_production_without_evidence() -> None:
    data = load_config().model_dump(mode="python")
    data["policy_bundle"]["production_eligible"] = True

    with pytest.raises(ValidationError, match="must be calibrated"):
        CompanionConfig.model_validate(data)


def test_default_policy_bundle_is_explicitly_uncalibrated() -> None:
    bundle = load_config().policy_bundle

    assert bundle.calibrated is False
    assert bundle.production_eligible is False


def test_experience_defaults_prioritize_continuity_without_extra_bubbles() -> None:
    config = load_config()
    assert config.open_loops.enabled is True
    assert config.experience.avoid_repeat_within_conversation is True
    assert config.experience.default_cancel_on_new_user_turn is True
    assert config.experience.afterthought_enabled_by_default is False
    assert "先听我说" in config.discourse.listen_only_phrases
    assert "不是那个" in config.discourse.wrong_reference_phrases
    assert "已经考完了" in config.discourse.outcome_reported_phrases


def test_experience_policy_override_changes_fingerprint(tmp_path: Path) -> None:
    override = tmp_path / "experience.toml"
    override.write_text(
        "[experience]\nsemantic_beats_enabled_by_default = false\n",
        encoding="utf-8",
    )
    changed = load_config(override)
    assert changed.experience.semantic_beats_enabled_by_default is False
    assert changed.experience.default_cancel_on_new_user_turn is True
    assert changed.fingerprint() != load_config().fingerprint()
