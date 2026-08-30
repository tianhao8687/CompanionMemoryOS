# Magic-number policy

“魔法数字”是会改变产品行为、却散落在实现中且没有名字、来源或验证的数值。陪伴记忆中的错误阈值会直接变成“认错人”“突然失忆”“保存太久”或“频繁打扰”，因此所有可调行为都必须集中管理。

## 唯一配置入口

行为参数统一放在 `companion_memoryos/defaults.toml`：

| 配置组 | 控制内容 |
|---|---|
| `retention` | 结构化记忆的短暂、短期、长期、敏感上限与候选复核窗口 |
| `retrieval` | FTS/语义/事件候选池、结果上限、字符与 token 预算、时效半衰期、CJK gram、匹配/歧义/置信阈值 |
| `ranking` | 词面、语义、实体、时间、显著性、时效、情绪、需要、连续性九项权重 |
| `tokenization` | 对最终 prompt 计数的 `tiktoken` encoding |
| `event_archive` | 原始事件开关、授权要求、助手/高度敏感开关、普通与敏感保留期 |
| `proactivity` | 默认授权状态、最小空闲、冷却、每日上限、负反馈静默期和相关理由要求 |
| `continuity` | 每种召回意图对十类记忆的连续性权重 |
| `policy` | 同意、敏感数据、wellbeing 和重复检测开关 |
| `server` / `database` / `security` | 回环监听、数据库等待和本地令牌参数 |

部署方只写差异 TOML，加载器做深合并。配置模型会验证：

- 默认上限不超过硬上限；
- CJK gram 最小值不超过最大值；
- `minimum_query_match ≤ hedge ≤ natural`；
- 敏感事件保留期不长于普通事件；
- 九项排序权重精确合计为 1；
- 每个 `RecallIntent × MemoryKind` 都有连续性值。

每次召回携带配置的 SHA-256 指纹，便于还原一次匹配、成本或误召回使用的参数。

## 代码中允许什么

协议版本、单位换算、哈希长度、浮点字节宽度和数学恒等值属于命名的结构常量，集中在 `constants.py`。策略与评分代码只引用配置或命名常量。

`tests/test_no_magic_numbers.py` 使用 Python AST 扫描：

- `policy.py`
- `scoring.py`
- `service.py`
- `temporal.py`
- `proactivity.py`

除 `-1`、`0`、`1` 这些结构性值外，新的裸数字会使测试失败。新增行为参数时必须：

1. 在 `defaults.toml` 增加有语义的键；
2. 在 `config.py` 增加类型、范围和关系验证；
3. 更新本文件及正反向测试；
4. 通过配置对象注入使用点；
5. 在真实或合成对话集上记录调参依据，而不是凭感觉把常量写进代码。

## 默认值不是永恒真理

当前值是 alpha 阶段的安全起点，不代表适用于所有语言、模型和关系节奏。生产调参应至少按以下指标评估：

- 小事召回的 Recall@k；
- 同关键词不同人物/时间的误认率；
- `natural` 断言的精确率；
- `ambiguous` 与 `no_match` 后的用户修复成本；
- 平均、P95 prompt token；
- 边界遗漏次数（目标为零）；
- 主动触达后的负反馈率和静默请求遵守率；
- 到期原始事件的残留正文数量（目标为零）。
