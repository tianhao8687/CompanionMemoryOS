# Magic-number policy

“魔法数字”是会改变产品行为、却散落在实现中且没有名字、来源或验证的数值。陪伴记忆中的错误阈值会直接变成“认错人”“突然失忆”“保存太久”或“频繁打扰”，因此所有可调行为都必须集中管理。

## 唯一配置入口

行为参数统一放在 `companion_memoryos/defaults.toml`：

| 配置组 | 控制内容 |
|---|---|
| `retention` | 从实际写入时间起算的结构化记忆短暂、短期、长期、敏感上限与候选复核窗口 |
| `retrieval` | FTS/语义/事件候选池、结果上限、字符与 token 预算、时效半衰期、CJK gram、匹配/歧义/置信阈值 |
| `ranking` | 词面、语义、实体、时间、显著性、时效、情绪、需要、连续性九项权重 |
| `tokenization` | 对最终 prompt 计数的 `tiktoken` encoding |
| `event_archive` | 原始事件开关、授权要求、助手/高度敏感开关、普通与敏感保留期 |
| `temporal_anchors` | 私人时间称呼开关、最短匹配字符、最大候选数和敏感数据开关 |
| `conversation_ledger` | 原始回合开关、授权、助手/高度敏感写入和作用域召回要求 |
| `epistemic` | 弱附和复核与不合格自述降级策略 |
| `memory_use_ledger` | 真实记忆使用记录开关；不含未经校准的表达冷却阈值 |
| `open_loops` | 未完成事项开关、授权要求和高度敏感信息开关 |
| `experience` | 当轮记忆重复抑制、默认打断行为、渠道分拍和默认关闭的补充拍 |
| `discourse` | 明确自然控制语的版本化短语族；不把短语命中伪装成概率 |
| `policy_engine` | LLM 外动作策略开关和无规则时的默认决定 |
| `policy_bundle` | 整套参数、模型与评测证据的版本身份，以及是否允许生产晋升 |
| `proactivity` | 默认授权状态、最小空闲、冷却、每日上限、负反馈静默期和相关理由要求 |
| `continuity` | 每种召回意图对十类记忆的连续性权重 |
| `policy` | 同意、敏感数据、wellbeing 和重复检测开关 |
| `server` / `database` / `security` | 回环监听、数据库等待和本地令牌参数 |

部署方只写差异 TOML，加载器做深合并。配置模型会验证：

- 默认上限不超过硬上限；
- CJK gram 最小值不超过最大值；
- `minimum_query_match ≤ hedge ≤ natural`；
- 敏感事件保留期不长于普通事件；
- 私人时间锚点的最短匹配字符和候选上限均为正数；
- 原始回合候选池、默认/最大注入条数满足正数和上下限关系；
- 九项排序权重精确合计为 1；
- 每个 `RecallIntent × MemoryKind` 都有连续性值。

每次召回携带配置的 SHA-256 指纹，便于还原一次匹配、成本或误召回使用的参数。

0.4 同时返回 `policy_bundle`。默认包是 `relationship-memory-zh-prototype`，并明确声明 `calibrated=false`、`production_eligible=false`。如果部署方把包标成可生产，配置验证会强制要求：已校准标记、feature schema、训练集、验证集、晋升报告的 SHA-256，以及实际模型指纹。哈希只能证明工件身份，不能证明数据有代表性；晋升报告仍需覆盖方言、角色、时间外和高风险切片。

## 代码中允许什么

协议版本、单位换算、哈希长度、浮点字节宽度和数学恒等值属于命名的结构常量，集中在 `constants.py`。策略与评分代码只引用配置或命名常量。

`tests/test_no_magic_numbers.py` 使用 Python AST 扫描：

- `policy.py`
- `scoring.py`
- `service.py`
- `temporal.py`
- `proactivity.py`
- `experience.py`
- `discourse.py`

除 `-1`、`0`、`1` 这些结构性值外，新的裸数字会使测试失败。新增行为参数时必须：

1. 在 `defaults.toml` 增加有语义的键；
2. 在 `config.py` 增加类型、范围和关系验证；
3. 更新本文件及正反向测试；
4. 通过配置对象注入使用点；
5. 在真实或合成对话集上记录调参依据，而不是凭感觉把常量写进代码。

## 默认值不是永恒真理

0.5 没有新增“安慰暂停几秒”“生气保留几天”“几轮后必须再问”等数值阈值。回访使用明确时间和状态转换；重复抑制使用实际 conversation 边界；补充拍使用宿主释放信号。`opened_at`、revision、beat ordinal、一次发送回执等属于事件/协议身份，而非相似度阈值。

`SILENT_MEMORY_KINDS`、`NATURAL_CALLBACK_INTENTS` 和表达目标指导仍是版本化源代码中的产品规则，尚未数据校准。0.6 的话语短语族集中在 `discourse` 配置中，命中结果是可解释规则，不输出伪造的置信概率；短语覆盖率仍需真实中文对话验证。API 字段长度/列表上限位于 schemas，SQL/SDK 资源限制也不全受 AST 扫描覆盖。因此新增文件进入扫描清单不等于“无魔法数字”已验收。本轮未运行扫描或校准。

当前值是 alpha 阶段的安全起点，不代表适用于所有语言、模型和关系节奏。生产调参应至少按以下指标评估：

把数字搬进 TOML 只解决“集中和可审计”，不等于已经完成数据校准。当前 Policy Bundle 只实现身份、证据门和生产资格阻断；检索、歧义、状态迁移、模型、prompt、索引 namespace 和资源限制的原子切换/回滚仍未实现。无法说明来源和失效条件的配置值仍属于魔法数字。

- 小事召回的 Recall@k；
- 同关键词不同人物/时间的误认率；
- `natural` 断言的精确率；
- `ambiguous` 与 `no_match` 后的用户修复成本；
- 平均、P95 prompt token；
- 边界遗漏次数（目标为零）；
- 主动触达后的负反馈率和静默请求遵守率；
- 到期原始事件的残留正文数量（目标为零）。
