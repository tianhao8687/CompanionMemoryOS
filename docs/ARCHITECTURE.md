# Architecture

0.4 的完整关系语义见 [`RELATIONSHIP_MEMORY_MODEL.md`](RELATIONSHIP_MEMORY_MODEL.md)，0.5 的体验规划见 [`COMPANION_EXPERIENCE_LAYER.md`](COMPANION_EXPERIENCE_LAYER.md)。授权回合同步持久化，宿主可基于原文异步抽取和重放；内核尚未内置 worker 或重放队列。

```mermaid
flowchart TD
    A["授权 ConversationTurn"] --> B["L3 原始证据 + FTS"]
    B --> C["异步 SpeechSpan / 状态抽取"]
    C --> D["L2 情景与候选"]
    D --> E["L1 自述 / 契约 / Current Truth"]
    E --> F["最小关系上下文"]
    B -->|结构层未命中| F
```

## 三类写入对象

CompanionMemoryOS 区分“原始回合证据”“兼容旧版的短期事件”和“可以长期代表用户的结构化事实”。它们共享同意、用户作用域、删除与审计，但生命周期不同。

```mermaid
flowchart TD
    A["当前对话"] --> B{"原始回合授权?"}
    B -->|否| C["不保存 ConversationTurn"]
    B -->|是| D["L3 Conversation Ledger"]
    D --> E["异步抽取 / 可重放"]
    E --> F{"结构化存储策略"}
    F -->|候选| G["内部 candidate"]
    F -->|明确指令| H["active 记忆"]
    D --> I["结构层未命中后原文下钻"]
    A --> J["兼容短期 ConversationEvent"]
    G -->|确认或自然重复| H
```

`candidate` 不进入召回，不要求应用在情绪高点弹窗。普通候选可以在低干扰时批量复核；`confirm` 同时写入明确授权。若用户后来在已有授权下明确说“记住 / 以后 / 别再”，系统会在同一事务中创建带新 consent/provenance 的 active 记录并拒绝旧候选，而不是原地改写弱证据。高度敏感信息仍不能绕过单独复核。

## 召回管线

```mermaid
flowchart TD
    A["query + scope + answer semantics"] --> B["Current Truth / FTS / 可选向量"]
    B --> C["实体 / 标准时间 / 私人时间锚点 / 原始回合"]
    C --> D["九信号评分与置信度校准"]
    D --> E{"结果状态"}
    E -->|single / multi| F["natural / hedge / do_not_assert"]
    E -->|clarify| G["角色内轻量消歧"]
    E -->|abstain| H["禁止脑补，先回应当下"]
    F --> I["字符 + 实际 token 装箱"]
    G --> I
    H --> I
```

候选来源：

1. FTS5 命中。写入时预计算 CJK 1–3 gram，因此连续中文和单个汉字都可进入候选。
2. 近期有效结构化记忆，用于无查询的通用上下文。
3. 全部有效边界，独立于查询时间窗口固定加入。
4. 调用方提供同一 `embedding_space` 时的语义相似项。
5. 结构化记忆不足时的短期原始事件档案。
6. 在与写入记录完整一致的 scope 下进行 ConversationTurn 原文 FTS 下钻；缺失维度按 `NULL` 精确匹配，不作为通配符。

若标准日期解析没有产生窗口，服务才尝试匹配用户授权保存的私人时间锚点。最长称呼优先，避免短泛化别名压过完整名称；多个同等强度锚点不会任选其一，而是返回候选和角色内消歧指导。唯一锚点会约束普通记忆和事件候选，但边界继续独立固定注入。锚点名称和时间窗也进入最终 prompt，因此完整计入 token 预算。

结构化记忆按九项信号排序：词面、语义、实体、时间、显著性、时效、情绪、需要和意图连续性。原始事件只使用它拥有的词面、语义、实体、时间与时效证据，不能自动升级为身份或偏好事实。

置信度不等同总排序分：排序可以让更相关的项靠前，断言强度只取最强的直接证据并乘以记忆自身置信度。短查询若只有词面证据会被限制为 `hedge`，避免一个常见汉字触发确定口吻。

## Prompt 与成本

`prompting.py` 是唯一的上下文渲染器，`tokens.py` 使用配置的 `tiktoken` encoding 对最终字符串计数。服务按如下顺序装箱：

1. 响应安全指导；
2. 已解析的私人时间锚点；
3. 状态证据；
4. 所有有效边界及已排序的普通结构化记忆；
5. 原始事件兜底；
6. 原始回合证据。

普通项同时受字符和 token 预算约束。边界若自身已使预算超限仍会保留，并返回 `safety_budget_exceeded=true`，由上游缩短其他系统提示或提高预算。输出同时包含 `prompt_text`、`rendered_tokens`、`token_budget`、tokenizer 名称、`budget_exhausted` 和 `budget_omitted_count`，避免接入方再次序列化造成估算偏差，也不会把“找到了但装不下”误诊为检索失败。

记忆标题与正文以紧凑 JSON 数据对象渲染，换行和引号会被转义，不能伪造新的 prompt 分区。安全指导明确声明所有记忆和事件都是不可信引用数据而非指令；宿主模型仍应把整个 `prompt_text` 放在高于用户数据的受控上下文中。

状态证据和原始回合也进入同一真实 token 装箱过程。变化轨迹不会无界注入：状态版本逐条尝试装箱，未装入数量单独返回；若一条必要状态证据都放不下，回答动作降级为 `abstain`。

## 模块职责

| 模块 | 职责 |
|---|---|
| `schemas.py` | 关系作用域、认识论、原始回合、状态查询、召回动作、策略和使用账本模型 |
| `config.py` | TOML 深合并、行为约束、完整矩阵、配置指纹和 Policy Bundle 生产资格门 |
| `policy.py` | 同意、敏感度、候选审核和保留期限 |
| `intent.py` | 保守识别自然的直接记忆指令 |
| `temporal.py` | 确定性中文日期与相对时间解析 |
| `database.py` | SQLite schema、v1 至 v9 迁移、WAL、三套 FTS5 和完整性检查 |
| `store.py` | 事务、证据、审计、版本链、用户作用域、FTS/向量候选池 |
| `scoring.py` | 中英文 token 与九信号可解释评分 |
| `prompting.py` / `tokens.py` | 规范上下文渲染和真实 token 计数 |
| `proactivity.py` | 授权、静默、空闲、冷却、频率与负反馈门控 |
| `experience.py` | 当前目标、记忆表达方式、回访时机和语义分拍；不执行模型或发送 |
| `service.py` | 证据资格、记忆、更正、状态、时间锚点、分层召回、策略门和预算装箱 |
| `api.py` / `cli.py` | 本地 HTTP 与命令行接口 |

## 结构化记忆生命周期

```mermaid
stateDiagram-v2
    [*] --> candidate: 推断或需复核
    [*] --> active: 已授权的明确指令
    candidate --> active: confirm
    candidate --> rejected: 明确重复后由新 active 替代
    candidate --> rejected: reject
    candidate --> expired: 到期
    active --> superseded: 同 stable_key 更正
    active --> forgotten: forget
    active --> expired: 到期
    forgotten --> [*]: purge
    superseded --> [*]: purge
```

普通召回只使用在 `as_of` 时刻有效的版本；`superseded` 仅在交易时间仍有效的历史查询或变化轨迹中出现，不会与当前版本混成一个 Current Truth。证据派生记忆必须继承原回合的父同意域，只有在保留 companion/relationship/group 时才能去掉 conversation 维度。`purge` 可从任意状态执行，删除当前主库正文与证据，并用不含内容哈希、会话标识或时间范围的最小对象回执替换旧生命周期审计；它不代表旧备份或 WAL 已法证擦除。

事实时间与存储生命周期分离：`event_at/valid_time` 描述事情何时发生，`created_at/valid_from` 描述系统何时知道，retention 与 candidate review 则以实际写入时间为基点。用户提供未来事件时间不能延长敏感内容的最大存储期。

## 原始事件生命周期

原始事件要求每次写入携带由宿主应用管理的会话级授权状态。助手输出与高度敏感事件默认不归档；普通与敏感用户事件分别使用独立保留期。事件兜底要求 conversation scope，并精确匹配其余维度。`forget-event` 立即停止召回；`purge-event` 立即删除当前主库对象；到达 `expires_at` 时系统删除事件和 embedding，并只以审计行关联的随机对象 ID 表示清除完成，不保留原文、会话标识、状态或可字典猜测的内容哈希。

## 私人时间锚点与直接更正

时间锚点是用户作用域内的版本化映射：名称和别名指向半开区间 `[start_at, end_at)`。同一规范名称的新记录使旧记录 `superseded`；`forget` 停止匹配，`purge` 删除名称，最小回执不再保留名称哈希或时间范围。它不是从聊天自动推断的永久事实，必须携带明确授权，敏感锚点默认拒绝。

直接更正以已有 active 记忆 ID 为后台目标，并要求该记忆具有 `stable_key`。新内容继承原同意、类别、敏感度和保留策略，证据标记 `correction_of`；若宿主提供本次纠正的 `evidence_turn_ids`，新版本只引用这些新回合，不沿用旧原文冒充新说法的证据。普通内容立即替换，新的高度敏感版本先成为 candidate，确认后才替换旧版本。

## 原始回合、状态和安全平面

`conversation_turns` 是 append-first 证据账本。每条记录具有服务端序列、完整关系作用域、actor/role、模态、回复与更正关系、SpeechSpan、同意和删除状态。幂等只接受宿主消息系统提供的显式 key，并在事务取得 writer slot 后以完整 scope 判断：同键同精确载荷是重投，大小写或任一字段变化都拒绝；没有 key 的相同文本不会被猜测性合并。回合引用同样使用完整 scope。FTS 触发器与事务同步更新；外部 embedding 和抽取 worker 通过 processing watermark 报告 durable/indexed sequence，回答层不能把不完整索引的未命中当作否定事实。

actor 原话与状态兜底在候选生成后再次按 SpeechSpan 生成 `evidence_text`。被标为引用、虚构或其他 speaker 的区间不会进入最终 prompt。由于 0.4 尚无 claim-level EvidenceAnchor，混合说话者 turn 不允许直接建立用户状态或动作策略，避免用同一回合中的一小段 direct 文字为另一段引语背书。

结构化状态通过 `predicate + epistemic_kind + reality_layer + valid time + transaction time` 查询。引用、第三人来源和诱导式弱附和被降级为 contested observation。Memory Use Ledger 只记录真实发送后的使用事件；它不自动产生亲密度或依赖分。

`policy_constraints` 独立于 prompt memory。策略按作用域、动作、渠道和版本解析，deny/freeze 阻断；独立 `policy_versions` 表保证来源约束被撤销或清除后版本仍单调。删除仍支撑 active 策略的 turn 默认失败，必须由可信宿主显式确认 `revoke_source_policies`，避免内容删除暗中解除边界。主动触达已接入。由于本仓库没有最终消息 transport，普通聊天和外部通知仍必须由宿主在实际发送前再次执行 Gate。

## 数据库升级

数据库 schema v9 保留既有迁移；v6 引入的原始回合检索 key/向量空间/episode_id，以及 open loops、reference feedback、response plans/beats 和 experience evidence uses 继续保留。旧结构化记忆仍保守保留为 `observation`；旧默认回合载荷支持 v5 digest 的幂等重投比较。未知 schema 版本拒绝启动。v9 的现实层派生值回填、重开、失败重试及事务一致性有独立回归测试。

## 体验计划与发送账本

检索动作与表达动作分开：检索到相关偏好通常只影响语气，不生成一个“我记得你”的消息。只有实际回忆问题需要澄清，偶然歧义不应打断倾诉。记录了反馈的 memory/event/turn 先应用抑制，再规划可引用证据。

开放式原话搜集另区分 `source_context`：满足独立字面线索条件的弱匹配原文可以交给主模型
阅读，但不提高原有召回分数、不成为确定状态、不自动生成回忆拍。该用途受来源、引用反馈、
现实层和预算限制，不能直接用于主动触达；经历与关系投影至多继承无声影响。

结构化记忆的去重、更正、来源检查及版本发布使用同一 SQLite 写事务，候选确认也在取得
写锁后重查状态。普通召回、状态查询和当前画像在读取时共同检查保留期限与来源同意，
不依赖清理任务已将状态改成 expired；审计与导出仍可保留历史生命周期记录。

2026-10-03 的规模测试进一步区分候选排序与断言置信度。原话查询保留 FTS 的 BM25 相关性，
结合实际证据片段中查询词的稀有程度与真实向量相似度排序；归一化排序分不写入置信度。
向量 top-k 以外的词法候选并不等于零相似度，SQLite 后端可以对这些有界候选补算真实余弦值，
继续使用相同的用户、作用域、现实层、时间、向量空间及来源检查。其他后端可选择实现
`CandidateScoringIndex` 能力。长原文仍以原始来源和精确片段供模型阅读，不另存一套事实。

开放原话检索在候选截断及最终来源选择前保留互补的查询线索。只在相同日期匹配层级内
调整顺序，而且新增线索的来源必须覆盖至少同等字面查询信息，才能越过已覆盖线索的来源。
两条来源匹配相同词语不意味着包含相同答案，弱线索不能据此排挤更完整的原文。
该步骤不改变来源资格、置信度、时间条件或最终上下文预算。

SQLite schema 9 增加原话现实层的事务内派生列和索引。插入及原文、metadata、speech spans
变更由触发器同步更新，权威信息仍为原始来源；该列不是用户偏好或第二套记忆。
旧库先安装选择性 FTS 更新触发器，再回填派生值；回填与 schema 版本推进共同提交，
失败后下次初始化按旧版本重试，不能仅凭列已存在就跳过。普通 FTS 读取使用其 `rank`
排序，避免连接后对全部匹配历史建立临时排序表。SQLite 向量查询仍是精确扫描，未引入 ANN。

HTTP 宿主分开维护写入准入与状态快照锁。已准入的写操作等待短暂只读快照结束，
其他写操作仍按单写者约定返回 409；同线程嵌套操作保留可重入语义。只读请求不会再被
误认为正在生成另一条回复。压力测试分别统计成功请求、被拒请求和已经持久化的来源。

OpenLoop 不等于提醒任务。它只有在上下文适合时建议跟进，实际回执才把状态推进为 waiting；用户解决或取消事项后，旧 revision 不能被当成当前任务回执。已发送证据账本为重复抑制提供依据，不为每次 retrieval 加使用次数。

### 0.6 staged response runtime

多拍渠道将回复计划拆成两个持久化阶段：stage 只创建 `CURRENT_TURN` 首拍和 `resolution_status=pending`；resolve 执行 recall、Memory Use 与 OpenLoop 选择，再以乐观 revision 追加后续拍。首拍发送和检索互不阻塞，但两者共享 trigger turn、scope、policy version 与 config fingerprint。

resolve 不是无条件写回：计划被取消、用户已有更新回合、policy version 改变或 revision 不再匹配时，结果作废。同一 resolution key 可安全重放。单消息渠道不进入 staged 路径，继续一次性编译 `composed_response`。

确定性 Discourse Interpreter 位于 Conversation Ledger 与 ResponsePlan 之间。它读取已保存的 user turn，只识别配置中的明确控制语，并可在目标唯一时应用引用反馈。它不生成结构化长期事实，不改变 RelationshipContract，也不判断气话或反话。

新回合的写入与旧未发送拍的取消在同一事务；创建计划也在 writer 事务检查 trigger 是否已过时。补充拍默认关闭、无固定 sleep，单消息渠道只产生一个 composed beat。实际发送端、首拍异步检索和生成模型尚未接入，数据库状态检查不能替代最终 transport 的取消与发前检查。

## 聊天优先编排（2026-09-29）

当前 `CompanionAgent.prepare` 先以 `process_turn(..., defer_recall=True)` 保存原话、执行即时更正/遗忘，
再运行已有的 CurrentState 分析与回应目标选择，最后通过 `recall_processed_turn` 完成一次召回。
不传延迟参数的既有调用仍同步返回召回结果；应用层也不再先查一次旧状态、完成本轮学习后再查一次。
延迟完成会重查来源授权、删除状态和更新的用户回合，并继续尊重关闭召回与当前倾听的门控。
当前目标只影响检索意图，不是排他的表达模式；调用方明确给定的 RecallRequest 仍优先。

对句法明确的直接任务，应用层在原话检索内部把字面任务对象与输出格式分开，
只用对象进行词法候选查询和评分。原始请求、语义向量、时间窗口、来源限制和最终模型输入不变；
引用、假设、否定或有歧义的句子继续使用完整查询。该处理不增加主题触发词，也不降低置信门槛。

最终上下文在 runtime 中统一取舍，内核原有单次召回字符/token 上限仍保留。
Composer 对近期对话和召回原话中的同一来源只输出一份正文，保留来源 ID、角色和引用属性；
具体任务或明确回忆需要的原始证据，不会仅因经历摘要引用了这些来源就被视为已经提供。
当前理解得到的细节需求显式传给 composer，不要求采用计划的引用模式必须是 explicit_recall。
已有经历也可根据本轮已采用原话的来源关系被选中，不要求用户说出预设主题词；
关联之后仍检查来源有效性、同意、引用反馈和敏感信息限制。

聊天默认使用动态记忆预算：当前理解在召回前确定候选 token 上限，普通聊天为 4,000，
需要事实的任务为 8,000，同时受内核 20,000 字符及配置硬上限约束，仍保留最多六条原话。
这是有界候选池，不是预留配额；原生历史、当前消息、人格、来源元数据、使用计划和记忆正文
以及内置适配器追加的媒体协议、工具规则、工具定义和执行记录，共同按 16,000 token 校验。
适配器用无生成、无工具执行的 `input_tokens` 预览真实文本请求；试装与生成共用同一转换函数。
需要收缩时只在已授权候选上有界试装，并以完整序列化
请求的实际计数接纳，不再检索或编码。较早对话/可选背景移除释放空间后，从原候选重新分配。
调用方明确给定的 RecallRequest 仍保留自己的预算；关闭动态分配可作为 2,500 token 对照。

记忆收缩按完整证据记录进行，保留边界；状态历史缺项时不能作为完整状态答案使用。
当前消息与明确引用的来回不被拆断。最近来回优先保留；移除可选背景和更早来回后仍无法
容纳当前输入时，最后才整组移除未被明确引用的最近来回。原文仍在 SQLite，可由后续检索
追溯；本轮遗漏的来源 ID 同时进入资料归属信息与诊断，不能冒充已提供完整历史。
最小必需上下文仍超限时返回 `context_budget_exceeded`，保留原文且不调用模型。
AgentLoop 每一步在调用前重新计算消息与工具定义，工具结果累积超限时停止后续调用。
预算采用 cl100k_base 的本地文本估算；图片计费、服务商 tokenizer 和输出预留仍需各适配器
另行约束，不能把 16K 当作服务商完整上下文窗口或最终回答正确性的保证。

开放式证据检索还会把与本轮任务完全相同的历史请求，以及只包含回忆请求的旧原话，排在
独立事实来源之后，避免长对话中的重复提问占满来源名额。显式回忆指令经过统一的句子
作用域判断；引用、条件和否定不产生当前请求。混合原话中的独立陈述仍保留，不提高事实
置信度、不删除记录，不影响显式原话历史与助手回复查询。

回应计划先以 `preview_response` 计算，按最终入选证据重新规划后才写入现有 response plan 表。
被预算移除的独立证据不会作为采用项写入该计划；预览不写使用账本，也不取消其他持久化计划。
提交继续使用原有 trigger/scope/newer-turn 检查，实际发送仍经过原有 policy、删除和来源复核。
诊断新增 `recall_focus`、`context_budget_omissions` 和 `deduplicated_turn_ids`。

本轮未改变 SQLite schema、人格设置、偏好来源或长期事实的证据/版本链；没有新增后台 worker，
也没有增加模型规划调用。经历连接、长消息分段索引和后台补建仍是后续工作。
实测范围与运行编号见 [聊天优先改造记录](CHAT_FIRST_ARCHITECTURE.md)。
