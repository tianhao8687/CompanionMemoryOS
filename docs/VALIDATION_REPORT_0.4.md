# CompanionMemoryOS 0.4 集中验证与对抗审查报告

验证日期：2026-08-31
验证对象：当前未提交工作树
结论：**原型级验证通过；生产发布仍为有条件 No-Go**

## 最终门禁

| 门禁 | 结果 |
|---|---|
| Pytest | 117 passed |
| 覆盖率 | 85% overall |
| Ruff lint | passed |
| Ruff format | 49 files formatted / check passed |
| Mypy strict | 18 source files, no issues |
| 依赖一致性 | `pip check` passed |
| 包构建 | sdist 与 Python wheel 均成功 |
| CLI 冒烟 | 新目录初始化、数据库完整性与 token 创建成功 |
| 工作树检查 | `git diff --check` passed |

唯一警告来自 FastAPI 测试依赖中的 Starlette `TestClient`：当前 `httpx` 适配路径已弃用并建议未来迁移到 `httpx2`。它不影响本轮测试结论，但需要随上游依赖升级处理。

## 对抗审查中确认并修复的问题

| 问题 | 用户风险 | 本轮处理 |
|---|---|---|
| 用正文与时间猜测回合重复 | 连续两个“嗯”被吞掉 | 只接受显式 `idempotency_key`；完整 scope 内串行检查；无 key 不合并 |
| 幂等载荷使用 casefold 比较 | `US` 与 `us` 被当成同一投递 | 改为精确规范载荷摘要，大小写及任一字段变化均拒绝复用 key |
| 候选原地升级 | 未知授权、弱来源被洗成已确认事实 | 同一事务创建带本次 consent/provenance 的 active 记录，再拒绝旧候选；失败时原候选不丢失 |
| 人工确认不更新授权 | active 记录仍显示 `consent=unknown` | `confirm` 明确写入 `consent=granted`；过期候选不能确认 |
| 相同正文跨现实层或稳定身份去重 | 角色扮演恋人设定污染现实关系 | exact duplicate 同时匹配 stable identity、subject、predicate、reality layer 与来源属性 |
| 引用文本只在排序时遮蔽 | 前任原话仍可能进入回答 prompt | 新增 `evidence_text`；引用、虚构和其他 speaker 区间不参与匹配，也不进入最终 prompt |
| 状态原文兜底未限定 actor | 第三人的“我喜欢你”可能被当成用户证据 | 状态兜底只查询当前用户 actor，并使用同一直接文本遮蔽逻辑 |
| 整 turn 证据缺少命题锚点 | 同一回合的一小段 direct 文本替另一段引语背书 | 在 claim-level anchor 完成前，含混合 speaker spans 的 turn 禁止晋升状态或动作策略 |
| 泛化标题生成稳定 key | 两条“偏好”互相覆盖 | 仅在有 predicate 时派生稳定身份；否则保持独立记录 |
| 状态比较使用整记录 hash | 同值不同标题被误判冲突 | Current Truth 比较规范化状态正文，不比较标题与类别包装 |
| 更正沿用旧证据 turn | 新说法被错误挂到旧消息 | 更正只绑定本次提供的新 `evidence_turn_ids`；删除旧证据不带走新版本 |
| 删除回执保留可猜测摘要 | 短亲密文本可被字典枚举 | memory/event/turn/anchor 回执不再保留内容哈希、session 或时间范围 |
| retention 以事实时间起算 | 历史导入立即过期，未来日期延长敏感保存 | retention、敏感 cap 与复核窗口改以实际写入时间起算 |

## 当前可以成立的结论

- 在现有测试边界内，关系作用域、原始回合精确召回、候选隔离、状态双时态、引用归因、策略版本、token 装箱和当前主库清除路径形成了可运行闭环。
- 未抽取的小事只要进入已授权 Conversation Ledger，仍可通过原文 FTS 下钻；语义转述没有可用语义索引时会保守 `abstain`，不会把未命中说成“用户没说过”。
- 现实、角色扮演、直接自述、观察、解释假设和弱附和已经有明确数据边界，不再依赖一个情感分数决定 Current Truth。
- 所有行为阈值仍集中在 Policy Bundle/TOML，并由配置约束和 AST 门禁监督；默认 bundle 明确 `production_eligible=false`，不能把“集中配置”冒充数据校准。

## 仍然阻断生产声明的项目

### BLOCKED

1. **100M token 尚未实测。** 没有目标设备持续写入、索引积压、磁盘满、断电、snapshot + delta 重建、embedding 迁移、尾延迟与成本证据。
2. **“彻底忘记”尚未闭环。** 当前只证明当前 SQLite 主库及同步索引路径；WAL/free pages、旧备份、provider、应用日志、媒体/CDN 和恢复后 tombstone 应用尚未法证验证。
3. **静态加密与密钥擦除未实现。** 原始亲密对话仍是 SQLite 明文，不能进入真实高敏用户测试。

### CONDITIONAL

- 本地 Bearer token 是服务级凭证，不是多租户用户身份；`user_id`、actor 与 direct-user attestation 必须由可信宿主从认证会话生成。
- SpeechSpan 解释器和 claim-level EvidenceAnchor 尚未内置；当前字符 offset 使用 Python Unicode code-point 语义，其他语言运行时必须显式转换并验证。
- 主库 purge 后没有独立幂等 tombstone ledger，旧 provider 投递仍可能以原 key 重新插入。
- Conversation Ledger 尚无自动保留期；长期原文保存策略、按类别暂停记忆和账户级删除编排仍由宿主补齐。
- 旧 `conversation_events` 没有 event mention 聚类与投递幂等；重复复述仍可能挤占候选。
- 外部 ANN、reranker、缓存和 provider 尚未证明 ACL 前置过滤与零跨 scope 泄漏。
- Policy Gate 只实际接入项目内主动触达；聊天 outbox、推送、邮件和最终 transport writer 仍需发送前二次 Gate。
- 尚无 ResponsePlan、用户打断取消、承诺/日历能力回执和语义分拍运行时。
- 117 个用例以确定性和合成场景为主，不能替代真实长期中文、方言、争执、撒娇、角色扮演与未成年人高风险切片评测。

## 发布裁决

可以继续作为 **Relationship Memory Engine 原型** 开发和接入 shadow 环境；不能宣传为已经支持一亿 token、能够彻底忘记、可安全保存高敏亲密数据或已经完成生产校准。

本轮未执行 commit、push、release 或任何远端上传。
