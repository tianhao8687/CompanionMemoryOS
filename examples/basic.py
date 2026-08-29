from pathlib import Path

from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConsentState,
    MemoryInput,
    MemoryKind,
    RecallIntent,
    RecallRequest,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore

config = load_config()
database = Database(Path("./example-data"), config)
database.initialize()
memory = CompanionMemoryService(MemoryStore(database), config)

memory.remember(
    MemoryInput(
        user_id="alice",
        kind=MemoryKind.BOUNDARY,
        title="称呼边界",
        content="不要使用过度亲密的昵称",
        consent=ConsentState.GRANTED,
        explicit_user_request=True,
    )
)

context = memory.recall(
    RecallRequest(
        user_id="alice",
        query="今天想聊聊",
        intent=RecallIntent.CHECK_IN,
    )
)
print(context.model_dump_json(indent=2))
