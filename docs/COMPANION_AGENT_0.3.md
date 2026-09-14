# CompanionAgent v0.3：独立关系语义与经历层

本阶段把四个维度拆开：Identity 回答“我们是什么关系”；Familiarity 回答“实际积累多少历史”；
Distance 控制当前表达距离；Dynamics 描述近期相处状态。Experience 则组织这些历史具体是什么。
默认不会调用新增解释模型或后台任务。

## 检查结果与架构选择

开发前检查了当前 Agent 的人格、关系存储/候选/阶段/编译、运行时和 CLI，以及 MemoryOS 的
Episode 模型、成员操作、消息解释、召回、时间语义、证据校验与 schema v8。
现有 Episode 已有可逆的 attach/detach/split/merge、现实层、参与者、作用域和 revision，
其 summary 在成员变化后会清空。因此保留 Episode 作为分组依据，在其上增加可重建的经历投影，
避免另造一套消息归属系统。

新增 `companion_agent/semantics.py` 与 `companion_agent/experience/`。经历层包含 models、store、
evaluator、service、compiler；继续使用同一个 SQLite 数据库、MemoryOS 原文和事务。
人格、关系、经历都有独立上下文预算，分别默认 1200、700、800 token。

## 关系语义修正

- `FamiliarityStage` 为 `new/familiar/established`。旧 Python 名称 `RelationshipStage` 保留为别名；
  `RelationshipStage.CLOSE` 和旧字符串 `close` 会解析成 `established`。
- 身份支持 `friend/close_friend/romantic_partner/companion/custom`，未确认时为 `undefined`；
  保留 labels、description、romantic、confirmed_by_user、确认时间与证据。
- 用户说“你以后就是我女朋友”可以当轮确认恋人身份。宿主可用 `initial_relationship_identity`
  或 `RelationshipService.initialize_identity` 记录用户在创建角色时明确选择的身份。
  配置有独立证据记录，不伪造聊天消息、活动天数、模式或共同经历。
- 疏远、争吵、长期未互动改变当前 Distance，不降低已积累的 Familiarity，也不自动删除恋爱身份。
  距离请求可撤销，身份改变仍需明确证据。
- 熟悉度只根据有效互动日期和实际跨度，加上可替代的模式/经历/里程碑证据判断；身份不参与门控。
  熟悉默认需 7 天实际跨度、3 个活动日期，以及稳定模式或至少 2 段共同经历或里程碑。
  长期稳定默认需 60 天实际跨度、12 个活动日期，以及 2 个模式、5 段共同经历或 3 个里程碑之一。
  用户单独纠正“认识半年”不伪造这些实际活动。一天大量消息不能满足跨度和日期条件。

旧 `close_*` 配置名为兼容保留，现表示长期历史阈值；旧近期活跃门控字段仍可读取，
不再用于遗忘历史。阈值是可调整的原型策略，未声称经用户研究校准。
默认小禾人格更新至 0.1.1，保留 Character Kernel，仅调整熟悉风格、关系不变量并增加身份风格。
恋人 + NEW 可以有双方允许的情侣表达，同时禁止虚构共同生活、已知习惯或长期内部梗。

## 经历的证据和语义

每条经历都有类型、私有关系三元组、参与者、时间、主题、完整 evidence_refs、事实片段、
重要性/情感显著度/关系显著度、生命周期、revision 与 anchor。

| 类型 | 语义 | 主体 |
| --- | --- | --- |
| user | 用户有来源的叙述，摘要保留“用户表示”的归属 | user_id |
| character | 角色上线后实际参与的对话行为 | companion_id，仍隔离到本用户关系 |
| shared | 有双方真实参与、多轮用户消息的共同交流 | user_id + companion_id |

助手原话只能证明角色作出了回应，不是用户人生事实的独立证据。
角色经历摘要描述“参与讨论和回应”，不把用户的离职、童年或私人生活挪到角色名下。
三个视图共享同一个事件 anchor；熟悉度只消费有效 shared 经历，召回也去重，不能三倍计数。

既定角色背景继续在 `agent_persona_sources` 中保存，输出显式标记 `source=canonical_backstory`、
fiction 和角色主体。新经历为 `source=lived`、真实对话证据，不能把阿灰等设定自动转成双方经历。
角色后天经历默认私有，不把用户 A 的故事展示给用户 B。

## 候选、连续性和生命周期

默认解释器先复用已有 Episode 成员关系。缺少 Episode 时，只对明确且唯一的主题连续性使用
本地规则，复用 MemoryOS 创建/附加事件段。支持离职选择、电脑配置、冲突修复、情绪支持、
共同任务和内部梗等常见主题；指代不唯一时不任意合并。
同一事件跨 conversation 可续接，但不能跨用户、角色、关系或现实层。
明确“另一次/重新考虑/又想辞职”会建立新 occurrence；已结束事件不因普通同词出现而自动续写。

经历先成为候选。shared 默认至少需要两个独立用户回合和真实助手回应才激活；
单条“这件事很重要”不再自动制造里程碑。候选决定支持 create/merge/update/close/promote/no_op。
状态包含 candidate、open、closed、dormant、superseded，30 天无进展的 open 可进入 dormant。
明确结果或关联 Open Loop 的完成可关闭经历；Open Loop 仍是原调度和事项状态来源。
宿主还可使用带 revision 的 `set_status`、`merge`，对错误分组进行明确修正。

经历摘要是确定性的证据压缩视图：保留首条与最近若干条完整短片段，长消息指向原文，
不让模型猜补摘要。原始引用可经 `trace` 下钻，再用 MemoryOS 读取完整原文。
成员被拆分/移出、原文删除/纠正、同意撤回或事实失效时，旧经历停止召回；
依赖它的关系历史支持随之失效。可重新 ingest 修正后的 Episode 重建经历。

高价值 shared 经历可晋升为 Milestone：综合真实多轮、多日、显著情绪、用户明确重要性、
持续交流等因素。持续数日的高显著度交流不必依赖一句固定“很重要”。
新运行时自动里程碑都引用 `experience:id`；旧已确认里程碑与可信宿主审阅接口仍兼容。

## 召回与上下文

经历召回按主题匹配与意义排序，优先 shared，合并重复 anchor 和被覆盖的事实。
明确回忆请求复用 MemoryOS 日历时间窗口，避免把本月经历当成上个月；
日历过滤依据已有证据日期，用户叙述中尚未解析的过去时间不会被编造成确定日期。
普通“今天老板又找我谈了”仍可关联先前未结束经历，不被“今天”强制切断连续性。

每轮最多选少量完整经历摘要。Composer 的七段结构保留，在 RELEVANT MEMORY 下增加
`relevant_experiences`，并去除已被该摘要覆盖的零散召回片段；近期对话仍保留必要交流顺序。
suppressed、silent_influence、clarify、soft_reference 约束沿原始证据继承，不能通过经历摘要绕过。
源内容被用户反馈抑制、现实层不符、跨主体或缺少敏感输入授权时不进入模型上下文。

## 完整运行链路

```text
MemoryOS.process_turn（保存原文、解释、Episode/Memory/State）
→ Response Goal / Memory Use Plan
→ 读取关系身份、熟悉度、距离、动态，预览本轮直接纠正
→ 召回已有经历 → 关系编译 → 人格编译 → Context Composer
→ Main LLM
→ 保存助手原话与发送确认
→ Episode 归属 → Experience 候选、合并、激活/关闭
→ Shared Experience 支持熟悉度，高价值经历产生 Milestone Candidate
→ 提交关系 revision 和日志
```

助手保存、Episode 附加、经历变更、候选回执、关系变更在同一 SQLite 事务内提交。
失败不生成“没发生过的双方经历”；成功重试复用持久化回复，候选和观察不会重复计数。
不在事务内等待远端模型。仍要求宿主串行同一会话，并用 revision 拒绝并发旧写入。

## 数据库与旧数据兼容

- MemoryOS 仍为 schema v8，原有表和原文不重写。
- relationship 组件迁移从 1 到 2，自动把当前模型和历史快照的 `close` 解析为 `established`，
  推导旧身份 type，保留 revision、entered_at、evidence、历史、边界、模式、里程碑、线程和动态。
- 增加 `agent_relationship_identity_configs`，保存用户创建时的明确身份配置证据。
- experience 组件版本 1，新增 `agent_experiences`、`agent_experience_candidates`、
  `agent_experience_revisions` 及 anchor/type 作用域索引。
- 旧 persona YAML 的 CLOSE 键仍能读取。空 identity_styles 默认值和枚举重命名不会使
  未改动旧文件的内容哈希失效；新默认 0.1.1 与旧人格版本并存。
- 旧 Episode 不自动全库扫描或调用模型。可显式 `ingest_episode`，逐段生成有证据的经历。

## 使用

```python
from companion_agent import CompanionAgent, RelationshipIdentityType, load_persona

agent = CompanionAgent(memory_service, load_persona(), main_llm,
    initial_relationship_identity=RelationshipIdentityType.ROMANTIC_PARTNER)
reply = agent.chat(request)
```

`initial_relationship_identity` 只在尚未确认身份时初始化，不覆盖后来用户的直接纠正。
旧 `agent.chat(request, RelationshipStage.FAMILIAR)` 可调用，但参数现在只作为临时距离请求，
不能伪造熟悉度。新集成推荐直接传 request。

```powershell
python -m companion_agent --data-dir .agent-data --identity romantic_partner --prepare "你好"
python -m companion_agent --data-dir .agent-data --relationship-status
python -m companion_agent --data-dir .agent-data --experiences
python -m companion_agent --data-dir .agent-data --experience-query "还记得我之前差点辞职吗"
python -m companion_agent --data-dir .agent-data --experience-trace EXPERIENCE_ID
python -m companion_agent --data-dir .agent-data --experience-history EXPERIENCE_ID
python -m companion_agent --data-dir .agent-data --experience-ingest-episode EPISODE_ID
```

`--prepare` 生成真实 messages，但不调用 Main LLM，也不会声称双方已经完成这轮经历。
`--identity` 是用户明确选择的创建配置，会写入独立审计证据。
经历 API 提供 `list_experiences`、`recall`、`trace`、`history`、`candidates`、`ingest_episode`、
`commit`、`merge`、`set_status`，接受显式作用域和可追溯证据，供后续 Reflection/Current State 复用。

## 当前边界与下一阶段

本版完成的是工程链路。默认语义解释仍是保守规则，不保证理解任意自由语言或隐喻；
跨话题消歧依赖已有 Episode 或明确连续性，模糊分组交给宿主/现有解释器。
摘要可追溯但偏事实摘录，尚未做真实模型表现、长期用户体验或大规模性能评测。
本地历史快照用于审计，删除源证据后公开接口隐藏失效正文，不等于物理擦除所有历史备份。

下一阶段优先实现 v0.4 Current State：让当前压力、冲突和修复有清楚的短期有效期、退出条件及证据；
之后再做 v0.5 全局预算分配和来源校验批处理，最后引入可审阅的 Reflection 候选。
本次没有新增后台心跳、主动外发、人格自我改写或真实模型实验。

## 2026-09-14 验证报告

| 检查 | 结果 |
| --- | --- |
| 全量 pytest | 339 passed；本阶段新增 27 项 |
| Ruff / 格式 | 通过 |
| 严格 mypy | 69 个源文件通过 |
| pip check | 无损坏依赖 |
| 人格组合预算 | 7 目标 × 3 熟悉阶段 × 6 身份 × 3 距离，共 378 种；602～831 token |
| 真实旧版数据迁移 | 使用已安装 v0.2 生成数据库，再由新代码迁移；身份、revision、entered_at、历史和旧人格哈希保留 |
| CLI | 创建时恋人身份 + NEW + 空经历成立；准备输入、状态查看和经历查看正常 |
| wheel 独立安装 | 通过；在独立目录验证模块导入、默认人格资源、旧 close 兼容、迁移及恋人 + NEW 的 CLI 输出 |

测试涵盖跨天离职经历合并和关闭、候选激活、观点视图去重、时间窗口、经历合并与 revision、
Open Loop 关闭联动、删除/移出后失效、跨主体与敏感隔离、记忆使用限制、失败不产生经历、
重试幂等、真实来源的里程碑晋升，以及无固定重要性语句的持续高显著度经历。
旧版有关阶段降级和单句里程碑的断言已按新产品语义更新，未取消其证据与安全隔离验证。
pytest 仅有两条第三方 Starlette/AnyIO 弃用提示，无测试失败；没有商业模型请求。
