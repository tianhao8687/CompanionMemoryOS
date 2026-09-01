# Open-source references and product choices

调研日期：2026-08-30。

这些项目提供了可验证的机制参考，但 CompanionMemoryOS 的目标不是把它们拼在一起。最终设计首先服从本项目的用户问题：小事能否找回、同关键词会不会认错、token 是否可控、未命中如何修复，以及确认流程会不会破坏情感代入。

## 参考项目

| 项目 | 值得借鉴 | 本项目的取舍 |
|---|---|---|
| [Mem0](https://github.com/mem0ai/mem0) | user/agent/run 作用域和增量抽取；没有抽出事实时原消息仍有价值 | 借鉴作用域与“抽取失败不等于消息不存在”；不照抄随版本变化的 ADD/UPDATE/DELETE 规则 |
| [Graphiti](https://github.com/getzep/graphiti) | episode/entity/fact、双时态及事实回溯到原始 episode | 借鉴 episode/fact/provenance 语义；继续以 SQLite 为事实源，正式 mention 聚类仍未实现 |
| [Letta](https://github.com/letta-ai/letta) | core memory、archival memory 与 conversation history 分层 | 借鉴核心状态、按需档案和原始历史分离；摘要只作索引，不替代原文 |
| [LangGraph](https://github.com/langchain-ai/langgraph) | thread checkpoint 与跨线程 store 分离 | 当前会话的未解决话题不能自动污染跨会话长期用户状态；0.4 先通过 conversation scope 建立隔离契约 |
| [SillyTavern](https://github.com/SillyTavern/SillyTavern) | 逐消息向量化、原消息回填和对向量检索/缓存副作用的公开警告 | 原回合可以回填，但向量只生成候选；不复制 AGPL 实现，也不把默认 chunk/Top-K 当真理 |
| [LongMemEval](https://arxiv.org/abs/2410.10813) | 回合粒度、多 key、时间检索、知识更新、拒答和端到端长期评测 | 作为 RelationshipMemoryBench 的方法参考；不以 Recall@K 单项代替最终回答与错误否定指标 |
| [AIRI](https://github.com/moeru-ai/airi) | 本地优先、多模态角色和持续陪伴强调“存在感”不仅来自文字 | 记忆层保持模型/形象/语音无关，但输出可直接供实时角色使用，避免后台术语打破角色感 |
| [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | 可替换 LLM、语音与形象组件，适合本地实时陪伴 | 延续可替换组件原则；本项目只解决可审计记忆，不把语音或角色状态塞进数据库核心 |

## 从用户问题反推的实现

| 用户担忧 | 采用的机制 | 为什么不是简单照搬参考项目 |
|---|---|---|
| “一件小事没写成长记忆，还找得到吗？” | 已授权 Conversation Ledger 先落原文，结构化未命中后下钻 FTS | 不要求每轮 LLM 抽取成功；但当前只有词法下钻，语义转述仍不能保证命中 |
| “同一个关键词出现很多次会认错吗？” | 实体 ID/别名、中文时间提示、`ambiguous` 状态 | 关键词只负责扩大候选，不负责最终断言 |
| “换个说法还能匹配吗？” | 可选 embedding 与词面候选合并 | embedding 是可选信号，不隐藏在不可审计的第二数据库中 |
| “完全没匹配上怎么办？” | `abstain` + 完整性清单 + 禁止错误否定 + 必要时索取一个线索 | 失败是正式输出；索引水位追平也不冒充本次已执行语义查询 |
| “会不会一直让我确认？” | 自然指令直接生效、候选内部化、低干扰复核 | 用户表达意图时不需要理解 `candidate` 或数据库术语 |
| “上下文会不会很贵？” | 唯一 prompt 渲染器 + `tiktoken` 实际计数 + 双预算 | 不用字符数或固定条数冒充 token 成本 |
| “它会不会突然来打扰我？” | 主动触达默认关闭、多门控、负反馈静默 | 记得用户不等于获得联系权限 |

## 明确没有采用的模式

- **只靠关键词 lorebook**：中文常见字和重复地点会产生错误熟悉感。
- **每轮覆盖一段“核心人格摘要”**：难以追踪哪句话改写了事实，也容易把短期情绪固化成人格。
- **必须使用知识图谱**：图适合关系和时间，但不应成为个人原型部署的前置条件。
- **无授权、无作用域地永久保存完整对话**：0.4 只接受宿主明确传入 `granted` 的关系/会话回合；原文仍未加密且彻底删除闭环未完成，因此不能直接用于真实敏感用户数据。
- **亲密度、依赖度或服从分**：它们容易把关系操纵伪装成产品指标。
- **每次写入都弹确认框**：正确性不能以持续打断用户情绪为代价。
- **让模型在未命中时“尽量接上”**：长期陪伴中，一次自信的假回忆比坦诚的不确定更伤信任。

## 后续参考方式

新增外部机制前，先用本项目的对抗性问题验证：它改善的是召回率、准确性、成本、可修复性、隐私还是代入感？如果只增加架构复杂度或互动黏性，而没有可测用户收益，就不进入核心。
