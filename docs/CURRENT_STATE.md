# CompanionAgent v0.4：跨轮次 Current State

本次补齐的是短期处境和交流要求的延续、更新与退出。状态用于调整最终回应策略，不生成固定回复，
也不改变关系身份、熟悉度或人格。原 `agent.chat(request)` 和 `agent.prepare(request)` 已接入。

## 检查到的能力与缺口

MemoryOS 已有原始消息、可选单次解释、ResponseGoal、MemoryUsePlan、时间事实和 OpenLoop；
Agent 已有关系动态、经历和上下文组合。原 `state_service` 管理有时间语义的事实，
不适合再承担短期对话指令；关系动态中旧“本轮倾诉”摘要也不能代表持续、可撤销的倾听要求。

因此增加小型 `companion_agent/current_state/`，仅保存临时处境、沟通需要和临时风格。
冲突与修复仍写入并读取 `RelationshipDynamics`，长期称呼限制仍使用 RelationshipBoundary，
事项结果仍更新原 OpenLoop；不维护第二份关系或事项真相。

## 实际行为

每轮先运行 MemoryOS，随后从已授权的用户原话提取明确更新、保存状态、检查有效来源，
再选择 ResponseGoal 和生成 MemoryUsePlan。计划中的来源限制会再次过滤状态；
必要时重建回应计划，避免被抑制的旧状态继续决定目标。

优先级是：本轮明确沟通要求 → 宿主明确目标/本轮具体任务 → 仍有效的沟通要求 → 原有目标。
例如旧倾听要求能越过近期消息窗口继续生效，但“帮我列两个办法”会在本轮切换为 PROBLEM_SOLVE；
“帮我修改自我介绍”直接协助修改，不先将整轮改成安慰。
倾听期间还会收住未经请求的角色背景引用，具体回忆或知识问题仍可以直接回答。

最终输入新增可预算的 `[CURRENT STATE]`，只包含当前可用的控制信息和必要处境，不回灌完整状态库。
状态默认无声影响，禁止播报标签、把过期当作恢复，或用紧张气氛要求用户安抚角色。
已完成事项不会连带清除其他独立压力；用户刚明确重申仍有压力时，该自述优先于“任务结束”的推断。

## 有效期与作用域

| 内容 | 默认延续 | 退出方式 |
| --- | --- | --- |
| 疲惫、近期睡眠不足自述 | 同一关系，12 小时 | 明确否定/纠正、到期或源失效 |
| 明确低落自述 | 同一关系，6 小时 | 纠正、到期或源失效 |
| 具体事项的压力 | 同一关系与话题，72 小时 | 相关明确结果、唯一关联 OpenLoop 完成、纠正或到期 |
| 倾听/建议需要、临时玩笑/引用要求 | 同一会话，8 小时 | 新要求、场景切换、主动重开或到期 |
| 明确“今天”的沟通/风格要求 | 同一关系，到用户日历时区的次日零点 | 新要求、退出或到期 |
| 对角色的冲突与修复 | 复用现有关系动态及其有效期，默认 7 天 | 明确修复或动态到期；不重置身份/历史 |
| “以后不要这样称呼我” | 现有长期关系边界 | 不由临时状态的到期撤销 |

这些时长是可调整的工程默认值，不是生理或心理恢复判断。过期只表示停止将旧报告当作当前依据。
“别再提了”控制引用，不表示事情已解决；用户主动重新开启时可释放临时引用暂停，
但不能据此绕过原有永久边界和 MemoryOS 的引用限制。

## 证据、隔离和一致性

状态只从真实、直接、已授权的用户消息产生。逐句区分第一人称、第三方、过去、假设和引用，
模型自述与角色扮演不生成用户现实状态。明确否定覆盖旧状态；不确定的自我猜测保留在原文，
不提升为确定的持久状态，也不为了填充状态记录而追问。

读取时重新验证源消息的同意、删除、现实层、主体、敏感输入授权以及 MemoryUsePlan。
本次也修正了引用限制查询：派生关系、经历和状态都检查原始来源会话的反馈，
避免跨会话读取时漏掉“不要引用”。被限制的关系动态也不再暗中决定表达距离。

每个逻辑槽按来源时间与服务器序号采用最新证据，迟到的旧消息不能回写覆盖较新状态。
同一 turn 的处理回执保证重试不刷新期限、不重复增加状态事件。
先选最新版本再判有效性，避免最新纠正被删除/过期后反而复活更早的相反指令。

用户已说出的交流要求会在回复准备时提交，即使 Main LLM 随后失败也仍可延续；
它不是双方共同经历，不需要等助手成功回复。经历和助手回复仍遵守 v0.3 的原子提交链路。
状态表不可用、结构损坏或预算失败时会记录降级元数据并回到原回复路径，不编造缺失状态。
底层 MemoryOS 数据库整体不可用时，仍遵循原有存储失败处理。

## 配置与迁移

```python
from companion_agent import CompanionAgent, CurrentStateConfig, load_persona

agent = CompanionAgent(memory_service, load_persona(), main_llm,
    current_state_config=CurrentStateConfig(
        communication_hours=8,
        fatigue_hours=12,
        emotion_hours=6,
        pressure_hours=72,
        max_context_tokens=450,
    ))
response = agent.chat(request)
```

设置 `enabled=False` 或 CLI `--no-current-state` 可保留原路径。
`ProcessTurnRequest.apply_low_risk_actions=False` 时，本轮明确要求仍能影响目标，但本模块不持久化自动更新。
没有新增外部服务或额外模型调用；可选 MemoryOS 解释器仍遵循已有凭证、授权和失败降级逻辑，
只复用其已有话语结果，不把它猜测的情绪自动转为用户事实。

首次启用自动新增 `agent_current_states`、`agent_current_state_receipts`、`agent_current_state_events`，
组件版本 `current_state=1`，原 MemoryOS schema v8、关系/经历 schema 和人格版本均不改变。
没有后台计时器：有效性在读取时计算。现有旧“本轮倾诉”关系摘要在新运行链路中不再冒充当前沟通要求，
新消息会逐步建立状态；不扫描整库重新推断过去。

日志增加 `current_state_status`、`current_state_tokens`、`current_state_ids`；主 Agent 版本为 0.4.0。
CLI `--current-state` 是明确的调试查询，可查看有效/过期记录和退出原因；普通聊天不会展示这些内容。

## 可复现连续示例

在项目目录并使用已安装依赖的 Python 运行：

```powershell
python examples/current_state_replay.py --data-dir .agent-data/state-replay
python -m companion_agent --data-dir .agent-data/chat --prepare "今天先别给建议，听我说就好。"
python -m companion_agent --data-dir .agent-data/chat --current-state
```

回放脚本走真实 Agent 准备/保存链路，Main LLM 使用传输桩，不调用商业模型：

| 轮次 | 输入/时间变化 | 实际策略 |
| --- | --- | --- |
| 建立 | 有点疲惫，暂时不要方案，让我说完 | LISTEN；保存疲惫和沟通需要 |
| 延续 | 后来又有新的事情发生，原话已离开近期窗口 | LISTEN；期限不因这轮被偷偷延长 |
| 改变 | 缓过来了，帮我列两个办法 | PROBLEM_SOLVE；不要求疲惫状态先消失 |
| 退出 | 推进 13 小时，再问二分查找 | DIRECT_ANSWER；旧短期状态不再注入，不声称用户已恢复 |

## 验证范围与局限

测试检查完整 `agent.chat` 或最终主模型输入，不仅断言数据库记录。
覆盖多轮/重启、当前覆盖、时间推进、独立压力、冲突对象与修复、永久边界、源删除/限制、
跨作用域、敏感输入、重试、迟到写入、可选组件失败与损坏结构等。
回归中旧 Agent 版本断言更新至 0.4.0，并将“持续倾听期间主动插入角色背景”的旧断言修正为抑制，
具体询问角色经历时仍验证能正常回答。

这属于数据、上下文和回应策略验证，尚未验证真实模型的自然对话效果。
规则目前偏保守，复杂省略主语、反话、隐含需要、多对象同名事项和更丰富的情绪描述并未全面覆盖；
模糊来源不应通过扩大标签来补齐。最值得继续改进的是在现有单次解释调用中增加带主体、时间、
原文跨度与不确定性的受约束状态候选，提高语言覆盖率，而不是新增一次必需模型请求。

## 实际执行的验证

2026-09-14，在项目目录执行（使用工作区 Python 虚拟环境）：

```powershell
python -m pytest
python -m ruff check companion_agent companion_memoryos tests/test_current_state.py examples/current_state_replay.py
python -m ruff format --check companion_agent tests/test_current_state.py tests/test_persona_layer.py tests/test_relationship_model.py examples/current_state_replay.py
python -m mypy companion_agent companion_memoryos
python -m pip check
python examples/current_state_replay.py --data-dir .agent-data/current-state-demo
```

结果：372 项测试通过，其中本阶段新增 33 项；Ruff、格式、严格 mypy（75 个源文件）和依赖检查通过。
pytest 有两条已有 Starlette/AnyIO 弃用提示，没有失败。CLI 已检查准备输入、有效/失效状态查询和禁用状态开关。
连续回放的当前状态文本为 157、157、159、72 token；这只是该实例成本，不是所有场景的上限测量。
以上均为本地数据、上下文和策略验证；真实 Main LLM 对话体验、广泛语言覆盖和长期负载测试未运行。

另执行 `python -m pip wheel --no-deps .` 并将 wheel 安装到独立目录。
在隔离导入路径下验证了 CLI、倾听状态持久化与增量迁移：MemoryOS 仍为 schema v8，current_state 为 v1。
开发环境继续保留可编辑安装。
