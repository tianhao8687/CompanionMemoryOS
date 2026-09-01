# Changelog

## 0.6.0 - 2026-09-01（alpha，集中工程验证通过）

- 新增确定性中文话语解释器，识别明确的倾听、建议请求、回忆提问、引用错配、停止引用、话题切换和事项结果；短语族进入配置与指纹。
- 新增 interpreted staged 入口，一次返回话语解释和当前话语首拍；低风险、可逆动作可自动应用，目标不唯一时返回 `needs_target`。
- 新增 staged ResponsePlan：首拍无需等待 recall；resolve 使用持久化请求快照、乐观 revision 和幂等 resolution key 追加后续拍。
- 首拍回执不再使 pending resolution 计划提前完成；新回合、取消、策略版本变化和 revision 变化阻止迟到检索写回。
- 单消息渠道保持原同步合并路径，不为模拟异步而拆消息；没有固定 sleep 或人为等待。
- 数据库升级到 v7，补齐 API、CLI、迁移和聊天运行时场景用例。
- 2026-09-02 集中验证通过：151 tests、84% overall coverage、Ruff、format、strict mypy、依赖检查、sdist/wheel、CLI 初始化与 SQLite schema v7 完整性均通过。
- 仍不包含聊天模型、后台 worker、outbox/transport、复杂反话识别、真实提醒或生产校准。

## 0.5.0 - 2026-09-01（未单独发布，已纳入 0.6 集中验证）

- 新增 Companion Experience Layer：记忆表达区分 silent / soft / explicit / clarify / suppress，非回忆问题的 incidental ambiguity 不触发机械追问。
- 新增 OpenLoop 的相关性回访、显式时间、用户重新开启、等待回复、解决/取消/延后和 revision 协议；无固定回访间隔。
- 新增 memory/event/turn 通用引用反馈与自然纠错入口；已有原文证据血缘参与错配抑制，未抽取的小事也能纠正。
- 新增已发送证据使用账本，在 conversation 内减少重复引用；用户主动问往事可重新召回。
- 新增 ResponsePlan、单消息合并、可选语义分拍、发送回执幂等、host-signal 补充拍和非归档输入 interrupt。
- 新用户回合与旧待发送计划取消同事务提交；延迟处理不能为过时 trigger 新建计划；已改变的回访事项不接受旧计划回执。
- 原始 ConversationTurn 增加 retrieval keys、同空间 embedding 和 episode_id；多 key 命中保留谨慎语气，事件回忆去重不改变原话历史查询。
- 数据库升级到 v6，新增体验层表与索引；迁移保留 v5 默认载荷的显式幂等键重投语义。
- 补齐 API、CLI、导出、迁移及体验场景用例与实现报告；全部纳入 0.6 集中验证。
- 仍不包含自动话语解释器、聊天模型、异步首拍加速、outbox、真实提醒、完整事件聚类或 100M 负载证据。

## 0.4.0 - 2026-08-30

- 新增关系作用域、Conversation Ledger、SpeechSpan 和原始回合 FTS 下钻；抽取失败不再等于证据丢失。
- 原始证据忘记后派生记忆停止召回；若来源仍支撑 active 动作约束，删除必须显式确认 `revoke_source_policies`，避免把“删内容”静默解释为“解除边界”。当前主库 purge 会保守清理直接派生记忆与使用账本。
- 新增直接自述、观察、解释假设、关系契约、世界设定与 AI 内部状态的认识论分层和资格降级规则。
- 新增有效时间与系统知晓时间状态查询，区分当时状态、后来追溯自述、关系契约和变化轨迹。
- 新增 `ANSWER_SINGLE / ANSWER_MULTI / CLARIFY / ABSTAIN` 动作，以及检索通道 watermark 和错误否定保护。
- 新增版本化 PolicyConstraint/Gate，并将主动触达接入 LLM 外策略检查。
- Policy Gate 使用独立单调版本计数器；即使来源约束被清除也不复用旧版本，并拒绝携带旧 `task_policy_version` 的缓存、重试或定时任务。
- 来源 PolicyConstraint 要求 user-authored turn 与可信宿主的 direct-user attestation，避免第三人引语或普通模型抽取直接改变动作边界。
- 新增 PolicyConstraint revoke/purge API 与 CLI；撤销 active 规则会推进版本，当前主库清除仅留下不含 action 的最小回执。
- 所有用户控制的实体名称进入 JSON 数据载荷，不再拼接到 prompt 元数据头；回答证据未进入 token 预算时动作降为 `ABSTAIN`。
- 原始事件/回合改为完整 scope 精确召回；派生记忆必须继承父同意域，第三人回合不能支撑用户自述，避免 conversation ID 复用或抽取提升造成跨关系泄漏。
- 当前主库 purge 会先清除对象旧生命周期审计，再写入不含内容哈希、会话标识或时间范围的最小删除回执；仍不声称覆盖 WAL、旧备份或 provider。
- 新增 Memory Use Ledger，返回累计使用与最近使用，不采用未经校准的固定冷却时间。
- 新增 Policy Bundle 清单和生产资格验证；默认参数包显式未校准、不可生产，不能用配置哈希冒充数据证据。
- 数据库升级到 schema v5，兼容 v1/v2/v3/v4 增量迁移；Turn 重投改用完整 scope 下的显式幂等键和精确载荷比较。
- 候选确认同步授予 consent；自然重复候选时原子创建新 provenance，重复判断隔离 stable identity、subject、predicate 与 reality layer。
- `UTTERANCE_HISTORY` 与状态原文兜底隔离 actor，并将引用/虚构/其他 speaker 区间从匹配文本和最终 prompt 一并剔除；混合 speaker turn 在没有 claim-level anchor 前禁止晋升状态或动作策略。
- 结构化记忆 retention、敏感上限和候选复核窗口改以实际写入时间起算，避免迟到历史立即过期或未来事件时间延长敏感保存期。
- 2026-08-31 集中验证通过：117 tests、85% overall coverage、Ruff、format、strict mypy、依赖检查、sdist/wheel 和 CLI 初始化均通过；仅有上游 Starlette TestClient 弃用警告。
- 明确 100M、彻底删除、静态加密、多模态、事件聚类、全渠道 Gate 和语义分拍仍未完成；本版本尚未发布。

## 0.3.0 - 2026-08-30

- 加入不打断对话的一句话记忆更正，沿用原授权和稳定身份，写入新版本并保留直接纠正证据；高度敏感内容仍需复核。
- 加入需明确授权的私人时间锚点、别名、版本链、遗忘、物理清除、导出和 API/CLI。
- 召回可把唯一的私人时间称呼转成时间窗口并计入最终 prompt；同强度多匹配返回歧义指导，不静默猜测。
- 时间锚点匹配长度、候选上限和敏感数据开关进入集中配置，数据库升级至 schema v3。
- 增加更正、私人时间消歧、隐私策略、迁移和 HTTP 接口的回归用例；本版本尚未执行验证或发布。

## 0.2.0 - 2026-08-30

- 加入已授权会话事件档案，为未升级的小事提供短期召回兜底；事件到期自动物理清除，助手与高度敏感事件默认不归档。
- 加入中文 n-gram、可选 embedding、实体、时间、情绪和需要的混合召回。
- 加入自然记忆指令、关系记忆、候选显式重复升级和稳定事实更正隔离。
- 加入 `natural / hedge / do_not_assert` 使用强度及 `match / ambiguous / no_match` 结果。
- 使用 `tiktoken` 对最终 prompt 做真实 token 预算，并保持边界固定注入。
- 将记忆正文渲染为转义数据并标记为非指令，阻止其伪造 prompt 分区。
- 加入授权优先、静默、冷却、频率和负反馈保护的主动触达决策。
- 数据库升级至 schema v2，提供 v1 原地迁移、实体、事件、embedding 与中文 FTS 回填。
- 扩充 CLI、HTTP API、对抗性回归测试、架构决策和开源参考说明。

## 0.1.0 - 2026-08-29

- 首次独立实现情感陪伴记忆层。
- 加入同意优先策略、候选审核、敏感数据期限和边界固定召回。
- 加入 SQLite/FTS5、证据、审计、版本链、遗忘、清除与导出。
- 将行为阈值与权重集中到 TOML，并加入防魔法数字测试。
