# CompanionMemoryOS

一个面向情感陪伴应用的、本地优先且同意优先的记忆基础设施。

它从 [`tianhao8687/MemoryOS`](https://github.com/tianhao8687/MemoryOS) 的可靠机制演化而来：SQLite 是唯一事实源、候选记忆先审核、证据与审计可追踪、事实更新形成版本链、用户可以遗忘或彻底清除。新项目去除了代码仓库、分支、任务和源码锚点等编程场景耦合，加入情绪、需要、边界、安慰策略、共同经历与陪伴连续性。

> CompanionMemoryOS 是“记忆层”，不自带聊天模型，也不是心理治疗或危机干预服务。

## 为什么独立建仓

原 MemoryOS 服务于 AI 编程工作流；情感陪伴涉及更敏感的数据与不同的错误成本。复制原项目会把大量代码检索和工程上下文带进来，所以本项目只保留经过验证的记忆原则，并重新设计领域模型与安全策略。原仓库不会被修改。

## 核心能力

- **明确同意**：用户明确要求记住且授权后，普通记忆才直接生效；推断内容进入候选区。
- **敏感信息最小化**：未知授权的敏感信息直接丢弃；高度敏感信息即使明确授权也必须再次审核。
- **边界优先**：已确认的 `boundary` 在召回中固定置顶，不会因为相关性低或字符预算小而消失。
- **当前表达优先**：过去情绪只作为证据，不能覆盖用户此刻的感受或要求。
- **版本化真相**：带 `stable_key` 的新事实会将旧事实标为 `superseded`，而不是悄悄覆盖。
- **可逆与可清除**：支持逻辑遗忘 `forget` 与物理删除 `purge`，并保留不含原文的审计记录。
- **本地事实源**：SQLite WAL + FTS5，无外部向量库或云端数据库依赖。
- **可解释召回**：返回词面、显著性、时效、情绪、需要和连续性六项分数。
- **无散落魔法数字**：期限、权重、召回上限、字符预算、CJK 分词范围等集中在 `defaults.toml`。

## 记忆类型

| 类型 | 用途 | 默认保留 |
|---|---|---|
| `identity` | 用户明确确认的身份事实 | durable |
| `preference` | 称呼、沟通、活动偏好 | durable |
| `boundary` | 禁止事项与互动边界 | durable、召回置顶 |
| `support_strategy` | 有效的安慰与支持方式 | durable |
| `commitment` | 双方约定与后续事项 | long-term |
| `ritual` | 固定问候、纪念或陪伴习惯 | long-term |
| `emotion_episode` | 有时间语境的情绪经历 | short-term |
| `shared_moment` | 值得延续的共同经历 | long-term |
| `wellbeing_signal` | 睡眠、精力等短暂状态 | ephemeral |

## 快速开始

要求 Python 3.12+：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
companion-memoryos init
```

明确保存一条边界：

```bash
companion-memoryos remember alice boundary "称呼边界" "不要叫我宝贝" \
  --consent granted --explicit
```

召回陪伴上下文：

```bash
companion-memoryos recall alice "我今天有点难过" --intent comfort
```

启动只监听回环地址的 API：

```bash
companion-memoryos serve
```

首次初始化会在数据目录生成 `api-token`。除 `/api/health` 外，请求需要：

```text
Authorization: Bearer <本地令牌>
```

## Python 用法

```python
from pathlib import Path

from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import ConsentState, MemoryInput, MemoryKind
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore

config = load_config()
database = Database(Path("./data"), config)
database.initialize()
memory = CompanionMemoryService(MemoryStore(database), config)

result = memory.remember(
    MemoryInput(
        user_id="alice",
        kind=MemoryKind.BOUNDARY,
        title="称呼边界",
        content="不要用亲密昵称",
        consent=ConsentState.GRANTED,
        explicit_user_request=True,
    )
)
```

## 配置与魔法数字

所有会改变产品行为的数字只在 [`companion_memoryos/defaults.toml`](companion_memoryos/defaults.toml) 中定义。可以传入只包含差异的 TOML：

```toml
[retrieval]
default_limit = 6

[retention]
short_term_days = 21
```

```bash
companion-memoryos --config ./my-config.toml show-config
```

配置在启动时做类型、范围、排序关系、完整矩阵与权重总和验证；每次召回都返回配置指纹，便于复现。测试会扫描策略、评分和服务层 AST，发现新的行为数字就失败。详见 [`docs/MAGIC_NUMBERS.md`](docs/MAGIC_NUMBERS.md)。

## 安全立场

- 不从沉默推断同意，不保存被拒绝的信息。
- 不优化依赖、排他、内疚或“只有我懂你”等操纵性关系指标。
- 不把历史情绪当作当前诊断，也不把推断记忆当成身份事实。
- 服务默认只绑定本机，并使用本地 Bearer token。
- 真正部署前仍应增加磁盘加密、备份策略、密钥轮换和所在地法规评估。

完整策略见 [`docs/MEMORY_POLICY.md`](docs/MEMORY_POLICY.md)，威胁模型与部署注意事项见 [`SECURITY.md`](SECURITY.md)。

## 开发验证

```bash
ruff check .
ruff format --check .
mypy companion_memoryos
pytest
```

当前阶段为可运行的 alpha 核心。路线与已知限制见 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)。
