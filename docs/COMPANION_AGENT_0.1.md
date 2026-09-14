# CompanionAgent v0.1 稳定人格层

已实现独立的 `companion_agent` 包。MemoryOS 保持历史事实、纠错和使用策略的职责，
人格层消费现有 `ResponseGoal`，按宿主传入的关系阶段生成角色上下文。
最终回复由可替换的 Main LLM 生成；实现没有按用户输入返回固定角色台词。

## 已交付

| 规格能力 | 实现 |
| --- | --- |
| 人格定义、身份、内核、七类目标风格、三类关系风格、不变量、示例 | `companion_agent/persona/models.py` |
| YAML 加载和校验 | `persona/loader.py`；支持大写/小写风格键，拒绝缺失项、未知字段、重复键、别名和不安全 YAML 标签 |
| 动态人格编译 | `persona/compiler.py`；只编译当前目标和关系阶段，最多两个匹配示例 |
| 人格预算 | 默认 1200；精确文本计数沿用 MemoryOS `TokenCounter`，可替换为宿主计数器 |
| 完整背景与开发者种子 | `persona_source/full_backstory.md` 与 `defaults/persona.example.yaml` |
| 角色经历存储/召回 | `character_memory.py`；独立版本记录，按 topic keys 匹配，再按 salience 排序 |
| 上下文组合 | `context/composer.py`；应用规则、人格、关系、记忆计划、证据、近期对话和当前消息 |
| 连续对话 | `runtime.py`；预处理、计划、编译、模型调用、回复持久化、记忆使用台账 |
| 可运行入口 | `python -m companion_agent` 或安装后的 `companion-agent` |
| 版本运行日志 | 回复 metadata 和 `companion_agent.runtime` logger |

## 本地使用

在项目目录安装：

```powershell
python -m pip install -e ".[dev]"
```

仅生成完整模型输入，不调用 Main LLM 或记忆解释模型：

```powershell
python -m companion_agent --data-dir .agent-data --stage familiar --goal listen --prepare "今天又加班到凌晨。"
```

`--prepare` 会持久化用户消息、运行 MemoryOS 本地处理并创建回应计划，输出
可直接传给聊天接口的 `messages` JSON。它用于检查真实输入，不能被当作无副作用的预览。

之后需要真实对话时，由宿主先设置 `MAIN_LLM_API_KEY` 环境变量，再运行：

```powershell
python -m companion_agent --data-dir .agent-data --stage familiar --allow-model --base-url "https://YOUR-HOST/v1" --model "YOUR-MODEL"
```

输入 `/quit` 结束。保留 data-dir、user、companion、relationship、conversation 参数即可接续历史。
`--persona` 指定自定义 YAML，`--api-key-env` 指定已有密钥环境变量，
`--memory-config` 可接入原项目记忆解释器配置。人格层和记忆解释器模型各自配置。
未配置记忆解释器时，仍使用原系统本地话语规则、原始消息持久化和召回能力；
不会伪装已经做过完整模型语义抽取。

## 嵌入宿主

```python
from companion_agent import CompanionAgent, RelationshipStage, load_persona
from companion_agent.llm import OpenAICompatibleMainLLM
from companion_memoryos.config import InterpreterConfig
from companion_memoryos.schemas import ConsentState, MemoryScope, ProcessTurnRequest

# memory_service 是宿主已初始化的 CompanionMemoryService。
main_llm = OpenAICompatibleMainLLM(
    InterpreterConfig(
        base_url="https://YOUR-HOST/v1",
        model="YOUR-MODEL",
        api_key_env="MAIN_LLM_API_KEY",
    )
)
agent = CompanionAgent(memory_service, load_persona(), main_llm)
request = ProcessTurnRequest(
    user_id="user-1",
    scope=MemoryScope(companion_id="xiaohe", relationship_id="r1", conversation_id="c1"),
    content="今天又加班到凌晨。",
    idempotency_key="host-message-001",  # 每条新消息唯一，重试保持相同
    consent=ConsentState.GRANTED,
    model_consent=ConsentState.GRANTED,
)
reply = agent.chat(request, RelationshipStage.FAMILIAR)
print(reply.turn.content)
```

`MainLLM` 是 `generate(list[ChatMessage]) -> ModelResponse` 协议。
其他供应商或本地模型可以由宿主写适配器，不需要改变人格定义。
内置 HTTP 适配器适用于兼容 chat/completions 的服务；不声称支持所有供应商原生协议。
它限制响应大小、设置超时、拒绝重定向和截断/工具调用输出，不自动重试。

宿主也可以调用 `agent.prepare(...)` 获取 `PreparedResponse`，或单独使用
`compile_persona_context` / `compose_context`。`prepare` 会按请求中的 model_consent
决定能否调用已配置的 MemoryOS 解释器；它本身从不调用 Main LLM。

回应目标优先级：宿主明确给出的 `response_goal` → MemoryOS 话语解释建议 →
可映射的召回意图 → `DIRECT_ANSWER`。人格编译器本身不重新判断用户意图。
关系阶段只能由宿主输入，不随单句亲密表达自动升级。

## 记忆、主体和使用限制

开发者背景保存在同一 SQLite 数据库的独立 `agent_persona_sources` 表中，
以 companion_id + persona_id + version 为主键，不写入用户事实表。
每条召回结果明确包含 actor_id、subject_actor_id、companion_id、persona_id、版本，
其 reality_layer 固定为 fiction。角色种子跨会话共享，不归属于某个用户，
因此不会被用户记忆导出误报成用户经历。
未知发生日期保持 null。v0.1 不自动从大段背景抽取种子，设计者手工整理并审阅。

正常用户记忆继续走现有 MemoryOS 存储、召回、纠错、主体和 reality_layer 处理。
组合器按现有 MemoryUsePlan 逐条选证据；没有决定的证据和 suppress 内容不进入提示词。
silent_influence、soft_reference、explicit_recall、clarify 保留原使用方式和主体。
被过滤的 turn fallback 只使用 evidence_text，不重新引入原消息被排除的片段。
角色种子仅按话题匹配少量召回，不全量注入；需要专注倾听的轮次不插入角色往事。
近期对话限制在同一用户、精确 scope、同一 reality layer，排除删除和无同意记录。
当前用户请求与历史数据放在 user 消息，角色示例不能当作真实共同历史。

此版本生成一条完整回复，继续使用 MemoryOS 的回应计划及发送确认机制。
主动关心调度和多段消息释放仍由原 MemoryOS/宿主负责；人格层不会擅自调度。
Main LLM 输出只作为 assistant 原话持久化，不自动升级成用户事实。
使用台账记录交给生成器的计划证据，不声称已经语义审计模型是否真的引用了每条内容。

## 预算、版本和可靠性

编译先去重，再保留完整内核、全部不变量、当前目标/关系风格和基本身份。
摘要和场景示例按剩余预算加入；不会从句子中间截断规则。
如果核心本身超预算，抛出 `PersonaBudgetError`，要求调整源配置或预算。
默认角色的 21 种目标/关系组合为 534～658 个 cl100k_base token。
这只是文本计数，其他模型的 tokenizer 和消息封装成本可能不同。

总上下文默认预算 16000（计数包括序列化 messages），超出时先移除最旧近期消息，
再移除角色种子；仍装不下则报错，不静默删除约束和 MemoryOS 证据。
人格预算和 MemoryOS 召回预算彼此独立。

相同人格版本再次安装是幂等的；内容哈希改变却不提升版本会报错。
每次成功回复持久化 persona_id、persona_version、model、response_goal、
relationship_stage、compiled_persona_tokens、供应商 usage，并通过标准 logger 输出。
日志不包含密钥、用户正文或回复正文。

失败保留已保存用户消息，并取消未完成回应计划。同消息键成功重试直接复用持久化回复。
模型生成期间的新用户消息、删除或策略变化会阻止旧回复写入。
回复保存和 MemoryOS 发送确认在同一 SQLite 事务中提交。
一个 Agent 实例串行处理 chat；多个进程/多个实例调用同一会话时，宿主应提供串行队列。
进程在远端调用成功而本地提交前崩溃时，重试可能再次产生远端请求。

## 验证范围

本次仅做功能与回归检查：模型/加载器校验、所有目标与关系组合、预算压缩、
种子主体/版本隔离、五种记忆使用方式、模拟模型连续对话、进程重建后的重复请求、
失败重试、消息失效及 HTTP 适配器协议。测试不连接商业模型。

2026-09-13 验证结果：新增 37 项、全量 279 项测试通过；Ruff 与严格 mypy 通过。
wheel 包包含 YAML、完整背景和 CLI 入口，并在源码目录之外完成安装后的 CLI 检查。
测试输出有两条第三方 Starlette/AnyIO 弃用提示，无失败。

按当前要求，真实模型连续对话实验、30～50 个行为评测场景、长对话人格稳定性
和 GPT/Claude/Gemini 模型对比留到后续统一进行；现阶段不宣称已验证人格表现质量。
