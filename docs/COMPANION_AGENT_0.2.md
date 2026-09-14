# CompanionAgent v0.2：关系模型

`agent.chat(request)` 现在会自动读取、评估并编译长期关系状态。
关系以 user_id + companion_id + relationship_id 隔离，同一对关系可以跨 conversation 延续。
人格 YAML 与 Character Kernel 保持不变，关系只影响当前表达距离与相关互动习惯。

## 模块与存储

`companion_agent/relationship/` 包含 models、store、service、evaluator、transitions、compiler。
SQLite 增量迁移增加以下表，不改变 MemoryOS 的 schema 版本或历史数据：

- `agent_relationship_models`：完整结构化快照、revision、身份、阶段解释、动态和活动证据。
- `agent_relationship_patterns/milestones/threads/boundaries`：按关系三元组和项目 ID 索引的子记录。
- `agent_relationship_revisions`：每次有效变更的类型、原因、时间、证据和前后快照。
- `agent_relationship_candidates`：待处理候选及 ADD/UPDATE/MERGE/RESOLVE/NO_OP 决策回执。
- `agent_schema_versions`：关系模块自身的迁移版本。

各表组合主键均以 user_id、companion_id、relationship_id 开头。
迁移可以重复运行；无法识别的新版本会明确报错。
本版 Agent 运行时仅接入双人私聊，拒绝带 group_id 的请求；MemoryOS 原有群组存储能力不变。

## API

```python
from companion_agent import CompanionAgent, load_persona
from companion_agent.relationship import RelationshipConfig, RelationshipKey

agent = CompanionAgent(
    memory_service,
    load_persona(),
    main_llm,
    relationship_config=RelationshipConfig(max_relationship_tokens=700),
)
reply = agent.chat(request)

key = RelationshipKey(user_id="u1", companion_id="xiaohe", relationship_id="r1")
model = agent.relationships.get_relationship(key)
timeline = agent.relationships.get_history(key)
summary = agent.relationships.get_summary(key)
```

`RelationshipService` 还提供 `record_pattern`、`record_milestone`、`open_thread`、
`resolve_thread`、`record_boundary`、`confirm_identity`、`update_dynamics`、`evaluate_stage`、
`get_relationship_context`、`get_candidates`、`remove_item`、`delete_relationship`。
记录 API 接受相应 Pydantic 模型；所有状态变更必须带有效证据。
这些写接口面向可信宿主和审阅后的结构化变更，不应直接暴露给未校验的模型工具调用。

统一候选接口是 `stage_candidates`、`preview`、`commit_candidates`。
`commit_candidates(..., expected_revision=n)` 支持乐观并发校验；候选回执防止重试重复计数。
`preview` 产生临时状态，不把尚未成功回复的一轮直接写成长期关系事实。
边界和直接纠正会进入本轮预览，因此本轮回复就能遵守。

每个 `evidence_ids` 项使用带来源的字符串，如 `turn:abc`、`memory:def`、
`event:ghi`、`open_loop:jkl`、`user_correction:abc`、`relationship_memory:def`、`milestone:m1`。
`RelationshipEvidenceRef` 可创建和解析这些引用。
`user_correction` 的 ID 指向用户原始纠正消息，不是新编造的历史事件。
角色背景、另一用户/另一角色的记忆、引用或角色扮演中的话、助手自述都不能充当直接关系证据。
长期模式按稳定 ID 合并，并追加不同证据；场景限定保存在 context_keys 中。

## 候选解释与当前能力

默认 `LocalRelationshipEvaluator` 使用保守、可审查的规则：

- “我们不是恋人”“我们是朋友”等明确关系定义。
- “我不喜欢你这么叫我”“你不用什么都顺着我”等直接边界。
- “我们其实已经认识半年了”及数字月份表达，使用日历月份纠正 started_at。
- 技术讨论直接给结论、情绪低落先倾听、重复决策反馈等互动偏好。
- 单次“哈哈你嘴真毒”只形成候选，不能据此确认用户喜欢毒舌。
- “今天不想听方案，只想吐槽”形成近期例外，不删除长期技术讨论模式。
- 用户明确标记重要的共同经历、冲突未解决及明确和解。
- 复用 MemoryOS 已激活边界/仪式/支持策略，以及具有有效源消息的 Open Loop。

默认规则不自称能够理解任意自然语言、反话或自动分析所有事件情绪。
宿主可注入 `RelationshipEvaluator` 协议实现，处理更丰富的解释和 Episode 信息；
输出仍须通过候选服务的主体、时间、现实层、同意、来源有效性校验。
未被规则覆盖的表达保留在原始 MemoryOS 消息中，不编造关系结论。

关系身份只接受直接确认；短期心情不等于稳定人格。
用户纠正认识时间，只改变关系起始时间，不伪造活动日期、聊天次数、模式或里程碑。
高价值里程碑要求明确重要性或可信宿主审阅，低于配置阈值的候选不会进入时间线。
Open Loop 仍由 MemoryOS 管理生命周期和调度，关系线程只作有来源的引用，v0.2 不增加后台提醒器。

## 阶段策略

默认原型策略可通过 `RelationshipConfig` 调整，尚未经真人实验校准：

| 变化 | 条件 |
| --- | --- |
| NEW → FAMILIAR | 至少 7 天、3 个不同互动日期、1 个稳定模式、2 个共同里程碑 |
| FAMILIAR → CLOSE | 至少 60 天、12 个互动日期、近 30 天至少 3 个互动日期、2 个稳定模式、3 个里程碑及用户明确的关系定义 |
| CLOSE → FAMILIAR | 45 天未互动，或有效期内明显冲突 |
| 收敛到用户指定距离 | 用户明确要求保持距离/做回普通朋友；在撤销前限制后续自动升级 |

阶段不是爱情标签，长期亲密也可以是朋友。
不会因同一天大量消息、单次示爱或单独的时间纠正跳级。
久别后的第一条消息不会抹掉此前的互动空档，恢复亲密表达仍需近期连续互动。
短期冲突动态默认 7 天有效；活动日期、持续时间和稳定模式各自独立，未使用总亲密分数。
每次阶段改变保留 reasons、evidence_ids 和 entered_at。

旧接口 `agent.chat(request, RelationshipStage.FAMILIAR)` 仍可用：只覆盖当前表达距离，
不会伪造关系历史或将人工标签持久化成自动阶段。
用户明确设置的距离上限仍优先于宿主的临时阶段覆盖。

## 动态上下文和预算

`compile_relationship_context(model, response_goal, current_user_turn)` 默认预算 700 token。
顺序为活动边界、相关近期动态、相关模式、未解决线程、相关里程碑、身份摘要。
所有活动边界完整保留；连边界都放不下时抛出 `RelationshipBudgetError`。
不对规则句子做字符串截断，不把整个关系库每轮都送给模型。

技术比较通常只加载相应直接判断偏好；“你最近跟以前不一样”等关系话题
才优先加载动态、相关历史和未解决冲突。动态过期后不继续影响当前回复。
关系摘要从结构化字段生成，仅为视图，不参与事实反向写入。

Composer 保留原有七段结构，RELATIONSHIP CONTEXT 改为真实编译结果。
关系编译预算独立于人格预算和 MemoryOS 预算。
来源被 MemoryUsePlan suppress 或用户引用反馈抑制时，依赖它的关系内容也被排除；
silent_influence/clarify 限制不会因转成关系摘要而升级为可明确回忆。
未获得敏感输入授权时，对应关系内容不进入模型上下文。

## 运行时提交与审计

一轮流程为：MemoryOS 保存与解释 → 记忆使用计划 → 读取关系 → 候选与临时预览 →
关系编译 → 人格编译 → Composer → Main LLM → 保存助手原话 → 提交关系更新。
助手消息、发送确认、关系 revision 和候选回执在同一个 SQLite 事务内提交。
模型失败不提交本轮候选；成功消息重试复用原回复，不重复形成模式。
并发关系 revision 冲突或生成期间的新消息会阻止旧回复提交。
沿用 v0.1 的串行宿主要求；不在数据库事务中等待远端模型。

日志 metadata 增加 `agent_version`、`relationship_revision`、
`relationship_revision_after`、`compiled_relationship_tokens` 和 `relationship_stage_source`。
原有人格版本、模型、目标等字段保留。

读取当前状态时会剔除已失效来源支持的派生内容，写入证据失效 revision。
公开历史/候选读取接口会隐藏含已失效证据的旧快照和正文。
历史原始快照仍保留在本地主库用于审计；永久删除关系可用 `delete_relationship(key)`，
它删除此关系状态、候选及历史，不删除 MemoryOS 原始用户消息。

## 命令行

```powershell
# 检查本地模型输入：不会调用 Main LLM；候选保持待提交
python -m companion_agent --data-dir .agent-data --prepare "我们不是恋人。"

# 查看当前关系、时间线、候选
python -m companion_agent --data-dir .agent-data --relationship-status
python -m companion_agent --data-dir .agent-data --relationship-history
python -m companion_agent --data-dir .agent-data --relationship-candidates
```

`--user`、`--companion`、`--relationship` 选择关系主体；`--max-relationship-tokens` 调整预算。
真实对话入口继续使用 `--allow-model --base-url ... --model ...`，现在无需 `--stage`。
本轮交付仅做本地工程验证，不进行真实商业模型或人格质量实验。

## 本地验证结果

2026-09-13：新增 33 项关系测试，全量 312 项通过。验证范围包括增量迁移、主体隔离、
模式合并和幂等、弱证据保留、直接纠正、阶段升降、久别后的距离、Open Loop 同步、
关系上下文预算及相关性、抑制/敏感证据、删除后的失效处理、并发冲突和原子回滚。
原 v0.1 人格功能检查保持通过。Ruff、格式、严格 mypy、依赖完整性检查通过。
CLI 验证了自动关系输入、状态查看与待提交候选；`--prepare` 没有提交关系候选。
wheel 已构建并安装到独立目录，验证了包导入、默认资源、增量迁移和关系 CLI；开发环境仍保持可编辑安装。
测试只使用本地模型桩，不据此声称已验证自然语言理解覆盖率或长期陪伴效果。
