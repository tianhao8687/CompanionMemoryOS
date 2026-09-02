# CompanionMemoryOS

一个面向情感陪伴应用的、本地优先、同意优先的记忆基础设施。

当前为 **0.7.5 实用接入 alpha（早期版本），整批实现与集中验证完成，真实聊天验收与生产发布尚未完成**。在 0.7.4 上新增普通消息统一入口、可选单次模型解释、轻量人物/别名解析及事件移出操作；默认仍只需要 SQLite，不启用模型也能工作。242 项测试通过，源码包/wheel 独立安装与实际命令行服务检查通过。

新接入请先看 [0.7.5 接入指南](docs/INTEGRATION_0.7.5.md) 和 [本批完成与验证报告](docs/RELEASE_REPORT_0.7.5.md)。0.7.4 基线保留在 [0.7 实现报告](docs/IMPLEMENTATION_REPORT_0.7.md)、[0.7 验证报告](docs/VALIDATION_REPORT_0.7.md) 和 [0.7 接入指南](docs/INTEGRATION_0.7.md)。既有分阶段回复协议仍见 [陪伴体验层](docs/COMPANION_EXPERIENCE_LAYER.md)。

它从 [`tianhao8687/MemoryOS`](https://github.com/tianhao8687/MemoryOS) 的可靠机制演化而来：SQLite 是唯一事实源、证据与审计可追踪、稳定事实形成版本链、用户可以遗忘或清除当前主库对象。这个独立项目重新设计了陪伴场景最在意的部分：小事找回、中文连续文本、人物与时间消歧、真实 token 预算、自然带入、关系演化和克制的主动关怀。

> CompanionMemoryOS 是可接入任意对话模型的“记忆层”，不自带聊天模型，也不是心理治疗或危机干预服务。

## 用户体验原则

- **不为记忆打断情绪**：在会话级采集授权已经开启时，“以后叫我小禾”“别再马上给建议”等自然指令可直接生效，不弹出机械确认框。
- **小事不必都升级成长记忆**：已授权的短期会话事件进入可过期的 episodic archive。它们可在结构化记忆未命中时兜底，适合“上次买的花是什么颜色”这类问题。
- **不确定就降低语气**：召回项标记为 `natural`、`hedge` 或 `do_not_assert`。多个相近经历返回 `ambiguous`；没有可靠证据返回 `no_match`，明确要求上游模型不要脑补。
- **先回应当下，再使用过去**：当前消息始终高于历史情绪、关系和偏好；消歧只有在答案确实依赖细节时才自然进行。
- **边界永不参与普通竞争**：有效 `boundary` 固定注入，即使超过 token 预算也不静默删除，并通过 `safety_budget_exceeded` 暴露给接入方。
- **主动关怀必须可控**：默认关闭，只有用户授权、非静默模式、有相关理由、达到空闲时间且通过冷却和每日上限时才允许触达。
- **不优化依赖感**：拒绝排他、内疚、威胁离开、替代现实关系等操纵性目标。
- **不替用户解释内心**：直接自述、观察、关系设定、气话假设、引用和 AI 内部状态分层保存；解释假设不能覆盖用户原话。
- **未命中不等于没说过**：召回携带各索引通道的覆盖水位；语义索引不完整时禁止作“你从没提过”的否定结论。

## 核心能力

- `process_turn()` / `POST /api/v1/turns/process`：保存原文 → 本地规则 → 可选单次模型解释 → 既有候选规则 → 回答上下文。失败不丢原话，重投可复用解释，无后台 worker。
- 轻量实体提案按有证据的名称和别名解析；同名不硬合并，未知主体不默认写成用户状态。跨天 Episode 继续支持 attach/merge/split/reassign，并补齐 detach。
- 中文 CJK 1–3 gram、英文 token、可选 embedding、实体、时间、情绪和需要组成混合召回；单个汉字也能进入候选，但只能谨慎使用。
- “今天 / 昨天 / 上周 / 上个月 / 去年 / 上次 / 最近”及明确日期参与时间排序；“上次”优先最近一条而不是随机命中同关键词。
- 人物 `id + name + aliases` 用于区分“小王的咖啡店”和“小李的咖啡店”。
- 默认 `tiktoken` 对最终实际注入文本计数，也可注入自己的 `TokenCounter`（词元计数器）；字符与词元双预算，返回完整注入文本、预算耗尽与省略条数。
- 普通推断记忆仍进入内部 `candidate`，不参与个性化；用户稍后用自然指令重复同一内容时，系统会在一个事务中写入带本次授权与证据的新 active 记录，再拒绝旧候选，避免把旧的未知授权或弱来源“洗白”。批量复核中的 `confirm` 本身代表明确授权，并把记录的 consent 更新为 `granted`。
- 稳定事实更正使用显式 `stable_key`，或由 subject + predicate + reality layer 派生稳定身份：新版本生效，旧版本成为 `superseded`。泛化标题“偏好/关系”不再自动生成 identity，避免不相关小事互相覆盖。
- 宿主识别到“不是小禾，是禾禾”后可调用一句话更正接口；它沿用原记忆授权，并可绑定本次纠正的新 `evidence_turn_ids`，不会把新内容伪挂到旧消息上，也不要求用户进入管理页确认。
- 已授权的“备考期 / 搬家那阵子 / 我们刚认识时”可保存为私人时间锚点；唯一匹配会自动限定召回窗口，同强度多匹配会自然消歧而不猜测。
- 原始事件按普通/敏感保留期自动从当前主库物理删除，只留下不含正文、会话标识、内容哈希或时间范围的最小对象回执；助手旧回复和高度敏感原始事件默认不保存，避免模型自我污染。
- 结构化记忆的复核窗口和保留期从实际写入时间起算，`event_at` 只表示事情何时发生；迟到导入不会刚写入就过期，未来事件时间也不能绕过敏感数据上限。
- SQLite WAL + FTS5 是唯一事实源；embedding 是可选、可重建的召回信号，不成为第二套真相。
- 可调期限、阈值、候选池、预算、权重和主动触达限制集中在 `defaults.toml`；协议字段边界在强类型 schema 中登记。AST 检查防止新增裸数值，但不等于已完成参数校准。
- 关系作用域隔离 user/companion/relationship/conversation/group；原始事件与回合只接受完整 scope 精确召回，复用同一 conversation ID 也不会跨关系串线。
- ConversationTurn 只使用宿主提供的显式 `idempotency_key` 合并重投；没有键的相同短句会作为两次真实表达保存，键复用但精确载荷（包括大小写、scope、speaker、时间、模态和 SpeechSpan）变化会拒绝写入。
- 由原始回合生成的长期记忆必须继承其 companion/relationship/group 同意域；只有保留父同意域时才允许从单次 conversation 提升为关系级记忆。
- 状态记录认识论类型、现实层、说话者、引用深度、诱导来源、有效时间、系统知晓时间和原始回合证据。
- 回答动作采用 `answer_single / answer_multi / clarify / abstain`，而不是总让向量 Top-1 决定真值。
- 独立 `PolicyConstraint` 在 LLM 外评估允许、拒绝和冻结；主动关怀已经接入，其他出站渠道由宿主负责二次 Gate。
- “删除边界来源消息”不会自动等同“解除边界”：存在 active 来源策略时必须显式确认 `revoke_source_policies`，并使所有旧 policy version 任务失效。
- 独立策略可通过 API/CLI 显式 revoke 或从当前主库 purge；两者都会保持 user 级策略版本单调，清除回执不保留策略动作正文。
- Memory Use Ledger 暴露使用次数与最近使用时间，支持减少重复梗和不合时宜的旧事重提，不内置拍脑袋冷却时间。
- 每次召回返回 Policy Bundle 身份；默认包明确未校准、不可生产，只有携带数据/晋升报告哈希和模型指纹的校准包才可通过生产资格验证。
- `MemoryUsePlan` 区分无声影响、自然引用、明确回忆、必要消歧和抑制；普通倾诉不会因为后台有歧义就被反复追问。
- `OpenLoop` 跟进面试、复查等未完成事项，只有相关且时机合适时才建议询问；真实发送后才记为已问，用户回答/取消后停止跟进。
- 原始回合可携带多个检索 key、同空间向量和 `episode_id`；错配反馈既可针对记忆卡，也可针对尚未抽取的原文与事件。
- `ResponsePlan` 提供无固定停顿的语义分拍和单条消息合并；新用户回合原子取消旧待发送拍，也可通过独立 interrupt 接口在不归档正文时打断。
- 多拍渠道可先创建只依赖当前话语的 staged plan；检索完成后用 revision + resolution key 幂等追加后续拍。首拍已发送不使待检索计划误完成，新用户回合会使迟到结果失效。
- 明确中文控制语可确定性识别为倾听、建议、回忆问题、引用错配、停止引用和话题切换；冲突表达不擅自裁决，错配目标不唯一时不自动修改。
- 运行时桥只返回识别、编排与证据引用，不自带聊天模型、worker、实时发送或日历提醒；不能把“已生成计划”说成“已给用户发出”。

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
  "以后别在我难过时马上给建议" --consent granted \
  --stable-key support-advice-boundary --predicate support_advice_boundary
```

召回时同时限制实际 token：

```bash
companion-memoryos recall alice "上次买的花是什么颜色" \
  --conversation-id session-42 --intent reflect --max-tokens 700
```

纠正一条已有稳定记忆，或登记私人时间称呼：

```bash
companion-memoryos correct MEMORY_ID alice "叫我禾禾"
companion-memoryos remember-time-anchor alice "备考期" \
  2026-03-01T00:00:00+00:00 2026-04-01T00:00:00+00:00 \
  --alias "冲刺那阵子" --consent granted
```

更正接口的 `memory_id` 由宿主在后台选择，用户无需看到数据库概念。私人时间锚点必须显式 `granted`；敏感锚点默认不保存。

结果中的 `retrieval_outcome` 有三种：

| 值 | 接入方应如何回应 |
|---|---|
| `match` | 按每项 `use_mode` 自然使用或谨慎试探 |
| `ambiguous` | 不展示审核界面；必要时在角色内询问一个人物、时间或地点线索 |
| `no_match` | 先回应当下，不编造共同经历；只有用户明确追问往事时才轻问一个线索 |

回答层还必须执行 `retrieval_action`：`answer_single`、`answer_multi`、`clarify` 或 `abstain`。即使 `retrieval_outcome=match`，若证据因 token 预算未进入最终 `prompt_text`，动作也会降为 `abstain`，不能凭候选元数据猜答案。

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
    MemoryScope,
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
context = memory.recall(
    RecallRequest(
        user_id="alice",
        scope=MemoryScope(conversation_id="session-42"),
        query="上次买的白色花",
        max_tokens=700,
    )
)
send_to_model(context.prompt_text, retrieval_action=context.retrieval_action.value)
```

长期陪伴应用应优先写入带关系作用域的原始回合，再异步抽取：

```python
from companion_memoryos.schemas import (
    ConsentState,
    ConversationRole,
    ConversationTurnInput,
    MemoryScope,
)

scope = MemoryScope(
    companion_id="companion-a",
    relationship_id="relationship-a",
    conversation_id="conversation-42",
)
memory.append_turn(
    ConversationTurnInput(
        user_id="alice",
        scope=scope,
        actor_id="alice",
        role=ConversationRole.USER,
        content="在校门口捡到一片心形叶子",
        consent=ConsentState.GRANTED,
        idempotency_key="provider-message-42",
        retrieval_keys=["幸运东西"],  # 由宿主生成/核验的索引线索，不替代原文
        episode_id="heart-shaped-leaf",  # 同一事件的多次提及可共享身份
    )
)
context = memory.recall(RecallRequest(user_id="alice", scope=scope, query="心形叶子"))
```

若应用已有 embedding 模型，可在写入时提供 `embedding + embedding_space`，召回时提供同空间的 `query_embedding`。不提供时仍可使用中文 FTS、实体、时间、情绪和需要召回。

## 配置与魔法数字

检索、评分、保留期和主动触达的可调默认参数集中在 [`companion_memoryos/defaults.toml`](companion_memoryos/defaults.toml)。协议长度、SQL/SDK 资源约束与校准证据仍需持续审计，不能据此宣称已彻底消除魔法数字。部署方可传入只包含差异的 TOML：

```toml
[retrieval]
default_limit = 6
default_max_tokens = 900

[event_archive]
retention_days = 90

[temporal_anchors]
minimum_match_characters = 2
max_matches = 4

[conversation_ledger]
require_scoped_recall = true

[experience]
avoid_repeat_within_conversation = true
afterthought_enabled_by_default = false

[policy_engine]
default_allow = true

[policy_bundle]
profile_id = "relationship-memory-zh-prototype"
calibrated = false
production_eligible = false

[proactivity]
maximum_outreaches_per_day = 1
```

```bash
companion-memoryos --config ./my-config.toml show-config
```

配置在启动时验证范围、排序关系、完整矩阵、权重总和与 Policy Bundle 生产证据门；每次召回返回配置指纹和 bundle 清单，便于复现。详见 [`docs/MAGIC_NUMBERS.md`](docs/MAGIC_NUMBERS.md)。

## 安全与项目边界

- 不从沉默推断采集同意；未获会话级授权的原始事件不会落盘。
- 高度敏感原始事件默认拒绝归档；部署方只有在具备单独授权与保护措施时才应覆盖该开关。
- 助手事件默认拒绝归档；助手承诺应写成有证据的 `commitment`，不能把旧模型输出循环强化为用户事实。
- 敏感结构化记忆要求明确同意；高度敏感信息仍必须单独复核。
- 服务默认只绑定本机并使用本地 Bearer token。真实部署还需磁盘加密、备份策略、密钥轮换和当地法规评估。
- 项目不负责从任意聊天自动提取结构化记忆，也不内置 embedding 或 LLM；这些保持可替换。
- 当前 embedding 余弦排序是本地线性扫描，适合个人和原型规模；大规模部署应接入可重建索引。
- `purge` 的 API/CLI 回执使用 `primary_store_purged`，只表示当前 SQLite 主库及同步索引已清理，不代表旧备份、provider、日志或磁盘空闲页已法证擦除。若 turn 仍支撑 active PolicyConstraint，必须先由可信宿主确认用户同时撤销该边界并传入 `revoke_source_policies=true`。
- “谁说过某句话”的 `utterance_history` 查询必须明确提供 `utterance_actor_id`；带 SpeechSpan 的引用或虚构区间既不会参与该 actor 的匹配，也不会重新进入最终 `prompt_text`。状态查询的原文兜底同样只读取当前用户 actor 的直接文本。

完整策略见 [`docs/MEMORY_POLICY.md`](docs/MEMORY_POLICY.md)，架构见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)，用户侧对抗分析见 [`docs/USER_ADVERSARIAL_ANALYSIS.md`](docs/USER_ADVERSARIAL_ANALYSIS.md)，开源项目取舍见 [`docs/REFERENCE_PROJECTS.md`](docs/REFERENCE_PROJECTS.md)，威胁模型见 [`SECURITY.md`](SECURITY.md)。

## 开发验证

```bash
ruff check .
ruff format --check .
mypy companion_memoryos
pytest
```

0.7.5 集中验证：242 项测试通过，整体语句覆盖率 89.27%；Ruff、格式检查、strict mypy、依赖检查、源码包/wheel 独立安装与实际 CLI/HTTP 接入通过，详见 [本批报告](docs/RELEASE_REPORT_0.7.5.md)。保留的 0.7.4 基线为 199 项测试，包含 20 个合成聊天场景共 640 条消息，检查最终注入证据而非仅检查候选召回。尚未执行一亿词元压力测试、真实性能测试或真实用户研究；固定模型输出和本地 HTTP stub 不能代替这些证据。
