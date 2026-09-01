# Relationship memory model

本文件定义 CompanionMemoryOS 0.4 的关系记忆语义。目标不是给每段关系计算一个分数，而是让每个结论都能回答：谁说的、是不是引用、属于现实还是角色扮演、何时成立、系统何时知道、依据哪些原始回合，以及现在是否仍有争议。

## 分层

| 层 | 当前实现 | 用途 |
|---|---|---|
| L0 当前对话 | 由宿主提供 | 当前消息、近期回合和本轮用户意图，始终高于历史推断 |
| L1 状态 | `MemoryRecord + predicate + epistemic_kind` | 当前自述、关系契约、边界及其双时态版本 |
| L2 情景 | 结构化记忆与旧 `conversation_events` | 共同经历和短期 episodic 证据；正式事件聚类仍未完成 |
| L3 原始证据 | `conversation_turns` | 授权原始回合、说话者、作用域、回复/更正关系和 SpeechSpan |

写入顺序必须是原始回合成功持久化后再异步抽取。抽取器停机不得阻止新回合进入 L3，也不得把“没有抽取结果”解释为“没有值得记住的内容”。

原始回合被逻辑忘记时，直接依赖该回合的派生记忆会同步退出召回并标记为 contested；原始回合被当前主库 purge 时，这些派生记忆与 Memory Use 会保守清除。若该 turn 仍支撑 active PolicyConstraint，forget/purge 默认拒绝，只有宿主确认用户同时决定解除该动作边界并显式传入 `revoke_source_policies=true` 后，才撤销/清除约束并推进策略版本。由于尚无字段级多来源重算，0.4 宁可删除需要重建的派生项，也不保留可能泄露已删除证据的摘要。

## 关系作用域

`MemoryScope` 包含：

- `companion_id`
- `relationship_id`
- `conversation_id`
- `group_id`

结构化记忆可存为用户全局、角色级、关系级或会话级；召回只接受全局父作用域和当前精确子作用域。原始事件与回合要求明确 conversation，并对 companion/relationship/conversation/group 四个维度做完整精确匹配：调用方省略的维度只匹配 `NULL`，不作为通配符。因此两个关系即使复用了同一 conversation ID，也不会混入同一原文候选池。

结构化记忆若引用原始回合作为证据，必须保留证据已有的 companion/relationship/group 同意域；只有父同意域完整保留时，才允许去掉 conversation 维度形成跨会话的关系记忆。没有父域的 conversation 证据不能直接晋升为用户全局记忆。直接自述与关系契约引用的证据还必须是 user-authored turn。0.4 的 `evidence_turn_ids` 尚不能指向具体命题，因此只要一个已标注 turn 同时包含引用、虚构或其他 speaker，就保守禁止它晋升状态/策略；纯 direct spans 才可用。没有 SpeechSpan 的旧回合仍依赖可信宿主归因，不能描述为核心已认证命题 speaker。

用户管理与导出接口可以查看该用户全部作用域，但这不等于某个角色可以把全部数据注入模型。

本地 API 的 Bearer token 目前是服务级令牌，`user_id` 与 actor 仍由宿主传入。真正多租户部署必须从认证主体生成不可被模型覆盖的 capability/envelope；当前契约不能被描述为已经具备生产级服务器身份隔离。

## 认识论类型

| 类型 | 含义 | 能否直接更新现实用户状态 |
|---|---|---|
| `direct_self_report` | 用户直接表达自己的偏好、感受或意图 | 仅在合格来源下可以 |
| `observation` | 发生过的表达或互动 | 不能自动等同长期内心状态 |
| `interpretation_hypothesis` | 气话、反话、认真改变等解释 | 不能；允许并存与 contested |
| `relationship_contract` | 用户明确选择的关系或角色设定 | 只在对应 reality layer 内有效 |
| `world_setting` | 剧情或世界观事实 | 不能覆盖现实资料 |
| `assistant_internal` | AI 角色内部风格状态 | 不能成为用户事实 |

现实层、角色扮演、引用和虚构由 `reality_layer` 分开。第三人、机器观察、嵌套引用，或者由 AI 诱导后的弱附和会降级为 observation/contested，并进入候选复核，而不是成为 Current Truth。

`SpeechSpan` 进一步记录原始回合内的字符区间、引用深度、归属说话者、目标、言语行为、现实层和模型指纹。0.4 提供存储契约，但不内置可靠的日常语言解释模型。

## 双时态状态查询

每条状态同时有：

- `valid_time_start / valid_time_end`：该状态被描述为在现实或剧情中的有效时间；
- `valid_from / valid_to`：系统何时知道并采用该版本；
- `event_at`：证据事件发生时间。

`StateQuery` 要求显式 predicate，并支持：

- `STATE_AT_VALID_TIME`
- `LATEST_SELF_REPORT_ABOUT_TIME`
- `CONTRACT_AT_TIME`
- `BELIEF_AS_KNOWN_AT`
- `CHANGE_TRAJECTORY`

因此“六月说过喜欢”“现在如何描述六月”“六月时系统知道什么”不会被压成同一个答案。`real_world` 与 `roleplay` 默认隔离。

`UTTERANCE_HISTORY` 还必须提供 `utterance_actor_id`。原始回合先按 actor 过滤；已经标注为引用、虚构或其他 speaker 的字符区间会从该 actor 的匹配文本中剔除，并使用遮蔽后的 `evidence_text` 编译 prompt，避免检索阶段排除后又把前任原话交给回答模型。状态未知时的原文兜底同样只接受当前用户 actor。

## 召回动作协议

`retrieval_outcome` 保留兼容的 `match / ambiguous / no_match`，新增面向回答层的动作：

| 动作 | 语义 |
|---|---|
| `ANSWER_SINGLE` | 单一证据足够且可区分 |
| `ANSWER_MULTI` | 查询允许多个答案或请求变化轨迹 |
| `CLARIFY` | 多个候选或状态解释仍合理 |
| `ABSTAIN` | 没有足够证据，或必要状态证据无法进入预算 |

当前仅完成结构化记忆、旧事件和原始回合层面的动作决策。可撤销的 episode mention 聚类、错误 merge/split 联合评测和 disclosure-safe 区分问题仍是下一阶段工作。

## 检索完整性

每次召回返回 `integrity_manifest`：

- 内置 raw-turn FTS 的 durable/indexed sequence；
- 外部抽取、embedding 或图通道上报的状态、水位和模型指纹；
- `negative_claim_safe`。

默认没有原始回合语义索引，因此即使 FTS 未命中也只能说“现在没有找到”，不能说“你从未提过”。外部 worker 只有在 durable 与 indexed 水位一致时才可声明当前 namespace 已追平；但水位追平仍不证明本次请求真正查询并消费了该通道。0.4 尚未定义外部语义结果回填契约，所以 `negative_claim_safe` 固定为 false。

## Policy Bundle 与魔法数字

召回除配置哈希外还返回 `policy_bundle`。原型默认包明确不可生产；任何包只有在配置中同时提供校准状态、feature schema、训练/验证数据与晋升报告哈希、模型指纹后，才允许声明 `production_eligible=true`。这是一道防止“配置文件里有数字就等于已校准”的工程门，不替代 RelationshipMemoryBench、分布外切片、shadow/canary 与原子整包回滚。

## Policy Gate

`boundary` 记忆仍负责为语言模型提供上下文，但不能作为唯一执行机制。`PolicyConstraint` 是独立安全平面：

- 按 action、channel 和完整关系作用域存储；
- 来源 turn 必须是 user-authored，并由可信宿主明确设置 `source_direct_user_instruction`；若已有 SpeechSpan，纯引用或虚构内容不能建立约束。这防止普通抽取结果仅凭外层 role 自动控制安全平面，但没有 span 时仍不能替代宿主级 speaker 认证；
- 来源 turn 只能在保留父同意域时从 conversation 提升到 relationship，不能提升为 companion-wide 或全局约束；全局策略必须由独立的可信用户操作建立；
- 删除来源证据与解除动作边界是两个决定；存在 active 来源约束时必须显式确认 `revoke_source_policies`，不能因普通内容删除而自动恢复触达或昵称；
- 版本化，后来的适用规则优先；
- 版本由独立的 user 级单调计数器签发，删除约束也不会倒退或复用版本；
- 独立策略可以显式 revoke 或 current-store purge；active 行被撤销/清除时推进版本，purge 只留下不含 action 的最小回执；
- `deny` 与 `freeze` 阻断动作；
- 最终发送可携带任务生成时的 `task_policy_version`；与当前版本不一致时 Gate 拒绝旧任务；
- 主动触达已经在决策后接入 Gate。

CompanionMemoryOS 尚不包含聊天 outbox、推送、邮件和最终 transport writer，因此不能声称所有出站渠道已经被同步拦截。宿主必须在渲染前和实际发送前调用同一 Gate，并拒绝携带旧 `policy_version` 的任务。

## Memory Use Ledger

系统记录某条记忆在什么 response group、作用域、用途和 use mode 下被真正使用。输出只保存摘要哈希，不保存生成文本。召回返回累计次数和最近使用时间，让回答规划器避免重复内部梗、翻旧账或过度回访。

写入使用记录时只接受 active 或历史查询中的 superseded 记忆；forgotten/rejected/expired 不能新增使用事件，未解决记忆也不能被登记为已断言。

0.4 不内置固定“几天内不能再说”的阈值，也不自动修改排名。此类规则必须进入经过评测的 Policy Bundle。

## 明确阻断项

以下能力没有因为 0.4 增加了数据结构就变成“已完成”：

1. 没有目标设备上的 100M token 持续写入、故障注入、重建和尾延迟证据。
2. SQLite 内容仍是明文；没有对象级密钥、WAL/free-page 擦除、备份 tombstone ledger 或第三方删除证明。
3. 没有 MediaAsset 密文存储、OCR/ASR/视觉观察的完整处理链。
4. 没有生产级异步队列、抽取器、事件聚类、ANN 或图索引。
5. 没有 Conversation Orchestrator、ResponsePlan、语义分拍、取消、outbox 或最终发送闸门。
6. 没有 RelationshipMemoryBench、真实长期用户校准或可原子切换/回滚的生产 Policy Bundle；默认 bundle 明确不可生产。

在这些阻断项解决前，项目只能称为关系记忆原型或关系记忆内核，不能承诺“支持一亿 token”“彻底忘记”或“生产级全渠道安全”。
