# 0.7.5：普通聊天接入

本版把“先保存原话、解释成候选、执行已有规则、准备回答上下文”收进一个同步入口。
沿用 SQLite、现有状态和回复计划，不增加后台 worker、向量数据库或 Agent 框架。

## 最短接入路径

`POST /api/v1/turns/process`，使用现有本地 Bearer token：

```json
{
  "user_id": "user",
  "scope": {
    "companion_id": "ai",
    "relationship_id": "relationship",
    "conversation_id": "chat"
  },
  "idempotency_key": "host-message-unique-id",
  "content": "我面试完了，等那家公司消息。",
  "consent": "granted",
  "model_consent": "granted",
  "calendar_timezone": "Asia/Singapore"
}
```

宿主不必为这条消息填写 predicate、MemoryInput、实体 ID 或 Episode ID。
用户 ID、角色和 scope 必须来自宿主会话身份，不能让模型自行填写。

- `consent`：允许保存原始回合。
- `model_consent`：允许本次解释器处理当前消息及本次范围内的少量历史上下文。
- 授权可由宿主沿用用户已开启的会话设置，不要求逐消息弹窗。
- 敏感历史默认不进入解释请求；明确允许时才传 `allow_sensitive_model_input=true`。
- 原始消息先提交，再调用模型；没有开启模型也能保存原文、执行明确本地规则和本地召回。

Python 对应方法：`CompanionMemoryService.process_turn(ProcessTurnRequest(...))`。
命令行对应：

```bash
companion-memoryos --data-dir ./data process-turn user relationship chat \
  "我面试完了，等那家公司消息。" --companion-id ai \
  --idempotency-key host-message-unique-id --consent granted \
  --model-consent granted --calendar-timezone Asia/Singapore
```

完整可运行的 Python 接入骨架见 `examples/process_chat_turn.py`。

## 可选的一次模型调用

默认关闭；安装与本地运行不需要模型账户。
需要内置 HTTP 解释器时，在现有差异 TOML 中加入：

```toml
[interpreter]
enabled = true
base_url = "https://your-model-gateway.example/v1"
model = "your-model-name"
api_key_env = "COMPANION_INTERPRETER_API_KEY"
require_api_key = true
max_input_tokens = 4096
max_output_tokens = 1536
timeout_seconds = 30.0
```

通过运行环境配置上述变量中的密钥；不要把密钥写进 TOML、聊天消息或仓库。
启动时用现有 `--config` 或 `COMPANION_MEMORYOS_CONFIG` 加载配置。
本地无密钥模型可以显式设置 `require_api_key=false`。

内置适配器发送一次 `POST <base_url>/chat/completions`：

- 默认 `max_completion_tokens`；只支持旧字段的网关可显式设置
  `output_token_parameter="max_tokens"`，不会偷偷切换协议并重试。
- 默认 `response_format={"type":"json_object"}`，返回后还必须通过本地强类型校验。
  JSON 模式只保证 JSON 形式，不能代替 schema 校验。
- 不调用工具、不自动重试、不跟随重定向、不拆成多个抽取请求。
- 可以显式选择 `instruction_role="developer"` 或 `json_mode=false`，
  但要由部署方验证所选模型的兼容性。
- 不额外指定 temperature 等解码参数；这部分沿用网关/模型默认，尚不是校准后的生产策略。

协议核对依据：[OpenAI Chat Completions 官方参考](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create)。
这不是对所有“兼容”服务的兼容性保证；本轮 HTTP 用例使用本地 stub。

## 自己接模型，不接框架

```python
from companion_memoryos.schemas import InterpreterContext, InterpreterOutput, TurnInterpretation

class HostInterpreter:
    def interpret(self, context: InterpreterContext) -> InterpreterOutput:
        # 在这里调用宿主已经使用的模型。原始消息此时已经保存。
        proposed_json = your_existing_model(context.model_dump(mode="json"))
        return InterpreterOutput(
            interpretation=TurnInterpretation.model_validate(proposed_json),
            model_fingerprint="host-model-and-prompt-version",
        )

service = CompanionMemoryService(store, config, turn_interpreter=HostInterpreter())
```

原有“宿主自行调用模型，再 POST /turns/{id}/interpretation”的路径继续保留。
自定义解释器应自行声明模型与提示版本、限制额外 prompt 和超时，不添加隐式多次调用。
核心的输入预估以内置消息封装为基准，不能证明自定义实现自行添加的 prompt 也受此限制。
内置提示的哈希只在真正使用该提示的内置适配器上记录；不会冒充宿主的提示版本。

## 一次解释包含什么

`TurnInterpretation` 同时承载原文片段、topics、entities、state_claims、
memory_candidates、open_loop_candidates、discourse_signals 和可选 episode_hint。
不要求每一类都有结果。明确短指令（例如“先听我说”）可以完全跳过模型。
自然变体可以由模型提出话语信号，最终仍由已有规则处理。

所有模型输出是候选，不自动成为 Current Truth。
“吐槽工作”不等于“决定辞职”；“最近没提某人”不等于“疏远”；用户的模糊附和也不是新证据。
这些语义限制写入提示并通过候选晋升规则约束，但不宣称真实模型已理解所有反话和方言。

## 人物与别名

模型使用局部 ref，不需要发明长期 ID：

```json
{
  "entities": [
    {"ref": "cat", "name": "团子", "kind": "pet", "aliases": ["小团"]}
  ],
  "state_claims": [
    {
      "title": "猫的习惯",
      "content": "团子喜欢在窗边睡觉",
      "subject_actor_id": "cat",
      "predicate": "resting_place",
      "entity_refs": ["cat"]
    }
  ]
}
```

只有当前原文确实出现的名称/别名才成为这次证据。
同一同意域、同一现实层、类型一致且名称精确唯一时，复用已有 ID。
明确表示“另一个同名的人”时，模型可提出 `action="new"`。
多个人同时符合时返回 `ambiguous`，不擅自合并；相关状态候选暂缓，原话照常保存，不触发强制追问。
单纯代词、没有可落到当前原文的名字时，自动主体状态可暂缓；模型不能直接挑一个目录 ID 绕过解析。

目录由现有解释记录和记忆中的证据派生，不新增实体表或知识图谱。
每条记录只保存本次真正出现的别名；遗忘早期别名证据后，不从后续摘要中把旧别名复活。
这是个人原型规模的精确解析，不是全自动共指消歧或跨语言实体链接器。

## 跨天事件与纠错

解释上下文带少量同关系的已有事件、话题、参与者和可回查的连续回合 ID。
模型提出 attach，核心检查关系、现实层、时间先后、话题交集、参与者及明确证据。
可选 `episode_max_gap_seconds` 仍由宿主提供，没有隐藏“几天内算同一事件”的阈值。

已有 attach、merge、split、reassign 保留。
新增 `POST /api/v1/episodes/{episode_id}/detach`：

```json
{
  "user_id": "user",
  "scope": {
    "companion_id": "ai",
    "relationship_id": "relationship",
    "conversation_id": "chat"
  },
  "turn_id": "wrongly-attached-turn",
  "expected_revision": 3
}
```

detach 只修改可撤销归属，重算事件时间并清空失效摘要，不删改原文。
解释记录中的 episode_id 是解释当时的回执；纠错后的当前归属以 turn.episode_id 和 episode API 为准。
跨 conversation 的事件维护使用同意域一致的 relationship scope。
默认 raw recall 仍是精确 conversation scope；整段跨会话事件可使用已有 episode turns 接口读取，
本版没有偷偷放宽所有原始历史的检索权限。

## 返回值和宿主下一步

| 字段 | 用途 |
|---|---|
| storage | 原文是否落盘、turn ID、重投标记及被取消的旧计划 |
| interpretation_status | 本次解释完成、复用、规则直达或降级原因 |
| interpretation | 候选记录、实体解析、事件归属和证据 ID |
| discourse | 当前更需要倾听、建议、纠错或回忆等指导 |
| response_context | 现有 recall 编译的最小上下文，不是已生成的聊天回复 |
| response_stale | 处理期间用户已发新消息；旧上下文不能直接发送 |
| model_calls | 本次解释器调用尝试次数，零或一；不等价于已收费的 HTTP 次数 |
| estimated_input_tokens | 预检封装估计值，不是账单 |
| model_usage | provider 实际返回的 usage；未提供或解析失败时为 null，不虚填为零 |

宿主仍负责生成聊天回复，并在真实发送前使用既有 Policy Gate / ResponsePlan / 发送回执。
本方法不会伪造提醒回执、通知用户、生成“我记得”首拍或安排人为停顿。
若需要即时首拍，继续使用已有 staged response 协议；本入口是同步内核，不替代聊天运行时。

同一 process 投递键重试，会复用原始时间戳和已成功的解释，避免重复候选及重复模型调用。
失败后宿主可以显式重试；修改正文仍必须使用新投递键。
不要把旧 `append-turn` 接口的同一键复用于不同 source envelope 的新 process 请求。
同一进程中的同 turn 并发会合并模型调用；多进程只保证派生写入幂等，不承诺模型费用 exactly-once。

## 预算与降级

本次解释不装载全部聊天。只取配置内的近期回合、相关实体和事件；scope/敏感过滤在外发前完成。
先裁掉旧上下文，再减少事件/实体目录；当前消息仍过预算则保留原文、跳过模型，不截断原文冒充已完整理解。
超长回合的默认检索查询使用 API 允许长度内的前缀，并返回限制原因；宿主可以提供独立的 recall_request。
自动 recall 排除当前提问本身，避免把用户刚问的假设当成过去的共同经历。

现实层过滤沿用 `RecallRequest.state_reality_layer`（旧字段名保留），现覆盖普通记忆、原始回合、
事件和语义候选通道；process 默认传入当前 reality_layer。旧无层级标记的原始事件按 real_world 处理。
对混合引语/剧情，宿主可信 SpeechSpan 的质量和模型语义仍有边界，不能将层级标签理解成读心能力。

模型超时、无密钥、HTTP 失败、不合法/截断输出：原话保留，状态为 failed，继续可用本地召回。
timeout_seconds 是标准库网络操作超时，不是整次请求的硬墙钟截止时间；
需要严格端到端 SLO 的宿主仍需管理请求期限和取消，不能把这个配置当成完整运行时。
删除原文或收到更新用户回合：迟到处理不会自动恢复删除内容或返回可直接发送的旧上下文。
所有预算是 0.7.5 原型资源策略，来源与局限见 `MAGIC_NUMBERS.md`，不是数据校准成绩。
