# Security

CompanionMemoryOS 处理的可能是高度私密的情感与关系信息。默认安全目标是减少采集、限制作用域、允许撤回，并让每次状态变化可追踪。

## 默认保护

- API 仅允许配置为回环地址。
- 首次启动生成高熵本地 Bearer token，并尽可能设置为仅当前用户可读。
- 所有读取、更新、遗忘与清除均要求 `user_id` 作用域匹配。
- 敏感信息没有明确授权时不会落盘；高度敏感信息必须经过候选审核。
- 原始会话事件要求独立的采集授权，使用较短保留期；到期正文、FTS 与 embedding 会物理删除。
- 私人时间锚点要求逐条明确授权，非普通敏感度默认拒绝；清除后审计不保留名称、名称哈希或时间范围。
- 直接更正必须匹配原记录的用户作用域与稳定身份；高度敏感的新版本在复核前不会替换旧版本。
- 原始回合必须带 conversation scope；事件/回合召回、显式幂等键与引用检查均使用完整 scope 精确匹配，不会因复用 conversation ID 而跨关系连接。调用方省略的维度只匹配数据库中的 `NULL`，不会被当作通配符。未提供 `idempotency_key` 时不按内容猜测重复，避免吞掉用户连续发送的相同短句。
- 派生记忆不得丢失证据回合已有的 companion/relationship/group 同意域；允许跨 conversation 形成关系级记忆，但禁止把某段私密关系证据直接升级为用户全局事实。用户自述或关系契约若引用原始证据，该证据还必须是 user-authored turn。
- 第三人、引用、角色扮演和机器观察不能直接晋升为现实用户自述；AI 诱导后的弱附和默认进入 contested candidate。
- `integrity_manifest` 暴露索引积压；即使外部语义水位追平，在本次查询结果回填协议完成前也禁止把未命中解释成“从未说过”。
- PolicyConstraint 在 LLM 外决定动作；来源 turn 必须是 user-authored，并携带可信宿主给出的 `source_direct_user_instruction` 证明，不能仅凭外层 role 或模型猜测静默升级。来源约束不能越过原证据的父同意域。删除仍支撑 active 约束的来源 turn 时，还必须显式设置 `revoke_source_policies=true`，防止“删掉消息”被静默解释为“解除边界”；撤销会推进独立单调版本。带旧 `task_policy_version` 的任务会被拒绝。主动触达已经接入，但宿主的最终发送渠道仍需再次执行 Gate。
- 注入 prompt 的记忆正文按 JSON 数据转义，不能用换行伪造系统分区；响应指导将全部记忆标记为不可信引用而非指令。
- SQLite 外键、WAL、事务和完整性检查默认启用。
- `purge` 删除当前主库中的活动正文、证据和同步索引条目，并以一条最小删除回执替换该对象此前可能包含 actor/session/action 元数据的生命周期审计；回执不保留内容哈希、会话标识或时间范围。它不是对 WAL、空闲页或旧备份的法证擦除证明。

## 部署方仍需负责

- 当前 Bearer token 是单机服务令牌，不是每用户身份凭证。多租户服务必须从已认证会话派生 `user_id`、actor 与 capability，禁止信任请求正文自行声明的身份。
- `actor_id`、SpeechSpan 归因、`explicit_user_request` 与 `source_direct_user_instruction` 由可信宿主提供；0.4 没有独立认证说话者、验证命题级 speaker 或验证抽取模型真实性的能力。多租户 HTTP 客户端不能被允许自行填写这些证明字段。
- `utterance_history` 必须绑定明确 actor；已标注为引用、虚构或其他 speaker 的区间会从该 actor 的词面匹配文本及最终 prompt 中剔除。没有 claim-level anchor 时，含混合 speaker spans 的 turn 不得晋升用户状态或动作策略。若宿主没有可靠 SpeechSpan，只能把 outer actor 当作未验证的 envelope 信息。
- 对设备或数据卷启用静态加密，保护备份并定期验证恢复。
- 不把 token、数据库、导出文件或用户正文写入日志、遥测与错误上报。
- 将召回的 `prompt_text` 放入受控的高优先级上下文，不要与可执行工具指令混为同一信任域。
- 多设备同步前实现端到端加密、设备撤销与密钥轮换。
- 为危机表达设计独立、人工审查过的安全流程；不要把本项目当作临床判断器。
- 根据实际经营地区完成隐私、未成年人、健康数据与删除请求合规评估。
- 在宣称“彻底忘记”前，证明主库、FTS、ANN、媒体、缓存、日志、provider、WAL/free pages、导出和旧备份恢复都不会使内容复活。

## 报告漏洞

请通过 GitHub Security Advisory 私下报告。报告中不要附带真实用户的对话、记忆数据库或访问令牌，可使用最小化的合成样例复现。
