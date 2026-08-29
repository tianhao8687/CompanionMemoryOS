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
