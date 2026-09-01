# Project status

状态：`0.6.0-alpha`（2026-09-02 集中工程验证通过；尚未生产发布，旧生产阻断项仍有效）

## 0.6 本轮新增（代码与集中用例已通过）

- 明确自然话语解释：倾听、建议、回忆提问、引用错配、停止引用、话题切换、事项结果；规则来自版本化配置，不调用 LLM。
- `interpreted-staged` 一步返回话语解释和首拍计划，聊天宿主不再手工拼装常见控制字段。
- 低风险自动动作：话题切换取消旧待发送计划；最近一次已发送证据唯一时，“不是那个/别再提”可直接形成反馈；当前话题唯一对应 OpenLoop 时可记录明确结果；不唯一时返回 `needs_target`。
- 真正分阶段的 ResponsePlan：首拍在历史召回前持久化；resolve 后追加检索/回访拍，使用 revision 与 resolution key 做并发和幂等保护。
- 首拍已发送但检索未完成时计划保持 active；新用户回合、策略版本变化或 revision 变化都会拒绝迟到结果。
- 数据库升级到 v7；新增 HTTP/CLI、v6→v7 迁移和聊天运行时集中场景用例。详见 [0.6 实现报告](docs/IMPLEMENTATION_REPORT_0.6.md)。
- 集中门禁结果：151 tests、84% overall coverage、Ruff/format、strict mypy、依赖检查、包构建、CLI 初始化和 SQLite schema v7 完整性均通过。详见 [0.6 验证报告](docs/VALIDATION_REPORT_0.6.md)。

## 0.5 本轮新增（已纳入 0.6 集中验证）

- Memory Use Planner：无声影响、自然引用、明确回忆、必要消歧和抑制；当前倾诉优先。
- OpenLoop：未完成事项、相关性与明确时间、用户重新开启、等待回复、解决/取消/延后和版本校验。
- Memory/Event/Turn 通用引用反馈、自然纠错和已有证据血缘抑制。
- 真实发送后的证据使用账本与当前 conversation 内重复引用抑制。
- ResponsePlan：单消息合并、无固定延迟的语义分拍计划、默认关闭的补充拍、幂等发送回执。
- 新回合与旧计划取消同事务；延迟检索完成的过时 trigger 不能重建计划；无正文 interrupt 接口。
- 原始回合多 key、可选向量、episode_id 候选去重；原话历史不按 episode 折叠。
- v6 表/索引、HTTP/CLI/导出接入和待运行的集中用例。详见 [本轮报告](docs/IMPLEMENTATION_REPORT_0.5.md)。

## 0.4 已有能力与当时验证结果

- 十类陪伴记忆，包括关系记忆、严格实体模型和稳定事实版本链
- 已授权自然指令的无弹窗生效，以及普通候选的显式重复升级
- 可独立授权、可导出、可遗忘且到期从当前主库物理清除的短期原始事件档案，助手与高度敏感事件默认禁用
- 中文 CJK n-gram FTS、可选 embedding、实体、时间、情绪与需要的混合召回
- `natural / hedge / do_not_assert` 使用强度与 `match / ambiguous / no_match` 整体结果
- “今天、昨天、上周、上月、去年、上次、最近”和明确日期的确定性时间提示
- 同关键词人物 ID 消歧、最近一次排序和更正后旧版本隔离
- `tiktoken` 最终 prompt 真实计数、字符/token 双预算和边界超限保护
- 主动触达的授权、静默、空闲、冷却、每日上限、相关理由和负反馈门控
- SQLite schema v1→v2 原地迁移、FTS 回填、WAL、证据哈希和审计
- 本地令牌、回环绑定、CLI 与 FastAPI 的事件/召回接口，以及 FastAPI 主动触达接口
- 配置指纹、完整连续性矩阵、权重校验与魔法数字 AST 测试
- 对未命中、关键词歧义、单汉字、中文长文本、语义转述、事件兜底、错误更正、token 超限和到期删除的回归测试
- 用户一句话更正 API/CLI：继承原授权、复用稳定身份、保留来源并形成版本链；高度敏感更正仍等待审核
- 需明确授权的私人时间锚点：别名匹配、时间窗召回、同强度歧义、版本化、遗忘、清除与导出
- SQLite schema v2→v3 兼容升级，以及更正、时间锚点和 HTTP 路径回归用例
- user/companion/relationship/conversation/group 关系作用域及父级全局记忆继承
- 授权优先、显式幂等键、可引用/更正、可遗忘/清除的 Conversation Ledger 与原文 FTS 下钻
- 原始事件/回合的完整 scope 精确召回，以及证据派生记忆的父同意域继承；复用 conversation ID 不会跨关系召回
- 原始回合忘记后派生记忆退出召回；删除仍支撑动作约束的回合必须显式确认同时撤销策略，避免把内容删除静默解释成解除边界；主库 purge 保守清除直接派生记忆与 Memory Use
- 主库 purge 用不含内容哈希、会话标识或时间范围的最小删除回执替换对象旧生命周期审计
- SpeechSpan 的引用深度、归属说话者、目标、现实层、言语行为与模型指纹契约
- 直接自述、观察、解释假设、关系契约、世界设定和 AI 内部状态的认识论分层
- 有效时间 × 系统知晓时间的状态点查询、历史认知与变化轨迹
- `ANSWER_SINGLE / ANSWER_MULTI / CLARIFY / ABSTAIN` 回答动作协议
- 原文、FTS 和外部语义/抽取通道的 durable/indexed watermark 与否定结论门控
- LLM 外版本化 PolicyConstraint/Gate、独立单调版本计数器与旧任务拒绝；主动触达路径已接入
- PolicyConstraint 的显式 revoke/current-store purge API 与 CLI；行为变更后版本推进，purge 审计移除动作元数据
- Memory Use Ledger：记录真实使用次数、最近使用时间和输出哈希，不保存回复正文
- Policy Bundle 身份与生产资格门：默认参数包明确未校准、不可生产，晋升必须携带数据/报告哈希和模型指纹
- SQLite schema v1/v2/v3/v4→v5 增量迁移及 0.4 对抗用例
- 117 个集中回归用例、85% overall coverage、Ruff/format/strict mypy、依赖检查、sdist/wheel 与 CLI 初始化门禁

## 已知限制

- 项目不从任意对话自动抽取结构化 `MemoryInput`；宿主应用仍需提供抽取器或规则，并把当前授权状态传入。
- 项目不生成 embedding；调用方必须在写入和查询时提供相同 `embedding_space`。当前本地余弦排序为线性扫描，适合个人或原型规模。
- 私人时间锚点需要宿主从自然对话中识别名称和起止时间；核心只负责授权存储、确定性匹配与消歧，不猜测未知边界。
- 一句话更正仍要求宿主把当前纠正映射到正确的原 `memory_id`；核心不会仅凭一句话自动选择可能影响隐私或边界的记录。
- Conversation Ledger 当前保存明文；尚无对象级静态加密、WAL/free-page 擦除、备份删除账本或第三方删除证明。
- Conversation Ledger 尚无自动 retention；主库 purge 后也没有独立 idempotency tombstone ledger，旧投递可能重新插入。
- SpeechSpan、认识论类型和 processing watermark 是强数据契约；0.6 只有明确短语的确定性话语解释，不是生产级语义/反话模型，也没有异步抽取队列或 embedding worker。
- `evidence_turn_ids` 尚不能定位命题级 span；混合 speaker turn 当前只能保守禁止状态/策略晋升。跨语言宿主还必须把 offset 转成 Python Unicode code points。
- 尚无可撤销的 episode mention 聚类。0.5 的 episode_id 由宿主提供，去重发生在候选池之后，不能证明前置挤占和错误 merge/split 已解决。
- Policy Gate 接入主动触达与回复回执；项目没有聊天 outbox、推送、邮件或最终 transport writer，宿主必须在渲染前和发送前再次执行 Gate。
- 0.6 已允许宿主先取首拍、再异步调用 resolve，但内核不创建 worker、不生成聊天文本、不实际发送，也不同步到外部 outbox。
- 没有 MediaAsset、多模态加密存储或日历提醒服务。OpenLoop 只能记录待跟进事项，不能证明提醒已经设置。
- 没有 100M token 真实容量与故障证据，禁止宣传为已支持一亿 token。
- Policy Bundle 当前只提供身份与晋升阻断，尚未完成模型、prompt、索引 namespace 与参数的原子切换、shadow/canary 和整包回滚。
- `purge` 只清理当前主库对象及同步索引，尚不能承诺旧备份、provider、日志和存储空闲页已“彻底忘记”。
- `candidate` 有 API 审核能力但没有图形化批量审核界面；设计上也不会在情绪对话中自动弹出。
- 单机 SQLite 不提供多设备同步、分布式并发或端到端加密；真实产品需要设备密钥、备份和同步方案。
- 审计日志没有签名链或外部只追加存储。
- 尚未进行真实用户研究、大规模中文召回基准、长期关系一致性红队或医疗合规认证。

## 下一阶段

1. 实现可重放的异步抽取队列、SpeechSpan 解释器与可撤销 episode mention 聚类。
2. 建立 `RelationshipMemoryBench`，分别报告写入覆盖、事件 Recall、歧义动作、时间真值、归因、拒答、安全和端到端回答。
3. 增加按 consent domain 隔离的可插拔 ANN namespace、snapshot + delta 重建和水位切换。
4. 增加对象/可擦除 segment 密钥、独立 tombstone ledger、恢复前删除应用和 forensic 删除验证。
5. 将已经通过工程门禁的 0.6 接入聊天生成、Commitment/Calendar 与真实能力回执，并保持 shadow 优先。
6. 将 staged ResponsePlan 接入真实 worker/outbox，以无人工延迟的 shadow 重放评估首拍延迟、用户打断、重问次数、token 与尾延迟。
