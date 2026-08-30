# CompanionMemoryOS

一个面向情感陪伴应用的、本地优先、同意优先的记忆基础设施。

它从 [`tianhao8687/MemoryOS`](https://github.com/tianhao8687/MemoryOS) 的可靠机制演化而来：SQLite 是唯一事实源、证据与审计可追踪、稳定事实形成版本链、用户可以遗忘或彻底清除。这个独立项目重新设计了陪伴场景最在意的部分：小事找回、中文连续文本、人物与时间消歧、真实 token 预算、自然带入、关系演化和克制的主动关怀。

> CompanionMemoryOS 是可接入任意对话模型的“记忆层”，不自带聊天模型，也不是心理治疗或危机干预服务。

## 用户体验原则

- **不为记忆打断情绪**：在会话级采集授权已经开启时，“以后叫我小禾”“别再马上给建议”等自然指令可直接生效，不弹出机械确认框。
- **小事不必都升级成长记忆**：已授权的短期会话事件进入可过期的 episodic archive。它们可在结构化记忆未命中时兜底，适合“上次买的花是什么颜色”这类问题。
- **不确定就降低语气**：召回项标记为 `natural`、`hedge` 或 `do_not_assert`。多个相近经历返回 `ambiguous`；没有可靠证据返回 `no_match`，明确要求上游模型不要脑补。
- **先回应当下，再使用过去**：当前消息始终高于历史情绪、关系和偏好；消歧只有在答案确实依赖细节时才自然进行。
- **边界永不参与普通竞争**：有效 `boundary` 固定注入，即使超过 token 预算也不静默删除，并通过 `safety_budget_exceeded` 暴露给接入方。
- **主动关怀必须可控**：默认关闭，只有用户授权、非静默模式、有相关理由、达到空闲时间且通过冷却和每日上限时才允许触达。
- **不优化依赖感**：拒绝排他、内疚、威胁离开、替代现实关系等操纵性目标。

## 核心能力

- 中文 CJK 1–3 gram、英文 token、可选 embedding、实体、时间、情绪和需要组成混合召回；单个汉字也能进入候选，但只能谨慎使用。
- “今天 / 昨天 / 上周 / 上个月 / 去年 / 上次 / 最近”及明确日期参与时间排序；“上次”优先最近一条而不是随机命中同关键词。
- 人物 `id + name + aliases` 用于区分“小王的咖啡店”和“小李的咖啡店”。
- `tiktoken` 对最终实际注入文本计数，字符与 token 双预算；返回完整 `prompt_text`、是否耗尽预算及省略条数，接入方无需再次猜测成本。
- 普通推断记忆仍进入内部 `candidate`，不参与个性化；用户稍后用自然指令重复同一内容时可无弹窗升级。
- 稳定事实更正使用 `stable_key`：新版本生效，旧版本成为 `superseded`，不会同时混入当前回答。
- 原始事件按普通/敏感保留期自动物理删除，只留下不含正文的内容哈希审计；助手旧回复和高度敏感原始事件默认不保存，避免模型自我污染。
- SQLite WAL + FTS5 是唯一事实源；embedding 是可选、可重建的召回信号，不成为第二套真相。
- 所有期限、阈值、候选池、预算、权重和主动触达限制集中在 `defaults.toml`，并由 AST 测试防止散落魔法数字。

## 记忆层次与类型

系统将“说过”与“长期认识用户”分开：

| 层次 | 作用 | 是否直接当事实 |
|---|---|---|
| 当前消息 | 用户此刻的表达 | 是，优先级最高 |
| 原始事件 | 已授权的短期对话小事 | 仅作 episodic 证据 |
| 候选记忆 | 系统推断、等待确认的结构化信息 | 否 |
| 生效记忆 | 用户明确表达或确认的稳定信息 | 是，仍需考虑时间和置信度 |
| 历史版本 | 已更正、遗忘或过期的记录 | 当前召回不可用 |

| 类型 | 用途 | 默认保留 |
|---|---|---|
| `identity` | 用户明确确认的身份事实 | durable |
| `preference` | 称呼、沟通、活动偏好 | durable |
| `boundary` | 禁止事项与互动边界 | durable、召回置顶 |
| `support_strategy` | 有效的安慰与支持方式 | durable |
| `relationship` | 重要人物、关系称谓与关系变化 | durable |
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

在用户已经授予采集权限后，存下一条普通对话小事：

```bash
companion-memoryos archive-event alice session-42 user \
  "下班路上买了一枝白色郁金香" --consent granted
```

用户自然提出边界时，无需再加 `--explicit`；系统会识别直接指令：

```bash
companion-memoryos remember alice boundary "安慰边界" \
  "以后别在我难过时马上给建议" --consent granted
```

召回时同时限制实际 token：

```bash
companion-memoryos recall alice "上次买的花是什么颜色" \
  --intent reflect --max-tokens 700
```

结果中的 `retrieval_outcome` 有三种：

| 值 | 接入方应如何回应 |
|---|---|
| `match` | 按每项 `use_mode` 自然使用或谨慎试探 |
| `ambiguous` | 不展示审核界面；必要时在角色内询问一个人物、时间或地点线索 |
| `no_match` | 先回应当下，不编造共同经历；只有用户明确追问往事时才轻问一个线索 |

启动只监听回环地址的 API：

```bash
companion-memoryos serve
```

首次初始化会在数据目录生成 `api-token`。除 `/api/health` 外，请求需要 `Authorization: Bearer <本地令牌>`。

## Python 接入

```python
from pathlib import Path

from companion_memoryos.config import load_config
from companion_memoryos.database import Database
from companion_memoryos.schemas import (
    ConsentState,
    ConversationEventInput,
    ConversationRole,
    RecallRequest,
)
from companion_memoryos.service import CompanionMemoryService
from companion_memoryos.store import MemoryStore

config = load_config()
database = Database(Path("./data"), config)
database.initialize()
memory = CompanionMemoryService(MemoryStore(database), config)

memory.archive_event(
    ConversationEventInput(
        user_id="alice",
        session_id="session-42",
        role=ConversationRole.USER,
        content="下班路上买了一枝白色郁金香",
        consent=ConsentState.GRANTED,  # 来自应用保存的会话级授权
    )
)
context = memory.recall(RecallRequest(user_id="alice", query="上次买的白色花", max_tokens=700))
send_to_model(context.prompt_text)
```

若应用已有 embedding 模型，可在写入时提供 `embedding + embedding_space`，召回时提供同空间的 `query_embedding`。不提供时仍可使用中文 FTS、实体、时间、情绪和需要召回。

## 配置与魔法数字

所有会改变产品行为的数字只在 [`companion_memoryos/defaults.toml`](companion_memoryos/defaults.toml) 中定义。部署方可传入只包含差异的 TOML：

```toml
[retrieval]
default_limit = 6
default_max_tokens = 900

[event_archive]
retention_days = 90

[proactivity]
maximum_outreaches_per_day = 1
```

```bash
companion-memoryos --config ./my-config.toml show-config
```

配置在启动时验证范围、排序关系、完整矩阵和权重总和；每次召回返回配置指纹，便于复现。详见 [`docs/MAGIC_NUMBERS.md`](docs/MAGIC_NUMBERS.md)。

## 安全与项目边界

- 不从沉默推断采集同意；未获会话级授权的原始事件不会落盘。
- 高度敏感原始事件默认拒绝归档；部署方只有在具备单独授权与保护措施时才应覆盖该开关。
- 助手事件默认拒绝归档；助手承诺应写成有证据的 `commitment`，不能把旧模型输出循环强化为用户事实。
- 敏感结构化记忆要求明确同意；高度敏感信息仍必须单独复核。
- 服务默认只绑定本机并使用本地 Bearer token。真实部署还需磁盘加密、备份策略、密钥轮换和当地法规评估。
- 项目不负责从任意聊天自动提取结构化记忆，也不内置 embedding 或 LLM；这些保持可替换。
- 当前 embedding 余弦排序是本地线性扫描，适合个人和原型规模；大规模部署应接入可重建索引。

完整策略见 [`docs/MEMORY_POLICY.md`](docs/MEMORY_POLICY.md)，架构见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)，用户侧对抗分析见 [`docs/USER_ADVERSARIAL_ANALYSIS.md`](docs/USER_ADVERSARIAL_ANALYSIS.md)，开源项目取舍见 [`docs/REFERENCE_PROJECTS.md`](docs/REFERENCE_PROJECTS.md)，威胁模型见 [`SECURITY.md`](SECURITY.md)。

## 开发验证

```bash
ruff check .
ruff format --check .
mypy companion_memoryos
pytest
```

当前阶段为 `0.2.0-alpha`。路线与已知限制见 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)。
