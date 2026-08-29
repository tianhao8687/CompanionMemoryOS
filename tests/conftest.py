from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from companion_memoryos.config import CompanionConfig, load_config
from companion_memoryos.database import Database
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore


@pytest.fixture
def config() -> CompanionConfig:
    return load_config()


@pytest.fixture
def service(tmp_path: Path, config: CompanionConfig) -> Iterator[CompanionMemoryService]:
    database = Database(tmp_path, config)
    database.initialize()
    yield CompanionMemoryService(MemoryStore(database), config)
