# CompanionMemoryOS 0.7.5 完成与验证报告

日期：2026-09-02

状态：代码、集中回归、源码包与 wheel 安装验证完成；真实模型与真人聊天验收待进行。

定位：可接入聊天宿主的单机 alpha 记忆层，不是已通过生产验收的完整陪伴产品。

## 本轮实际完成

| 文档中的目标 | 0.7.5 落地 |
|---|---|
| 普通消息不再要求宿主手写一堆结构 | 新增 process_turn、HTTP /api/v1/turns/process、CLI process-turn |
| 一次解释得到多个维度 | 同一 TurnInterpretation 提出片段、话题、人物、状态/记忆候选、未完成事项、话语信号和事件建议 |
| 模型只提出，核心决定 | 模型无数据库修改接口；原始回合先提交，候选仍经过现有 remember / open-loop / episode 规则 |
| 降低模型接入成本 | 可选 OpenAI-compatible HTTP 解释器，或注入简短 TurnInterpreter 协议；默认关闭，无新服务 |
| 人物与别名连续 | 从现有证据派生轻量目录；只记录本次原文出现的名称，唯一匹配复用 ID，同名不硬合并 |
| 一件事跨多天持续 | 给解释器提供有界事件目录与连续回合 ID；现有 attach 校验继续负责归属，新添 detach 纠错 |
| AI 自身连续性 | 沿用 companion subject；阻止把 AI 输出提案自动归为用户状态或无主体共同经历 |
| token 与失败处理 | 输入预检、上下文裁减、输出/响应大小上限、明确超时、无隐式重试；usage 与预估分开 |
| 自然对话优先 | 精确短指令可走本地规则；倾听时不强行回忆，重复纠错不再次落到更旧引用上 |
| 兼容已有宿主 | 旧解释 API、状态 API、双时间语义、ResponsePlan、Tokenizer/SemanticIndex 接口保留 |

沿用 SQLite schema v8，没有新增数据库表、迁移、图数据库、消息队列或微服务。
从参考文档吸收的是简单接入、多维候选、事件连续性和证据链，不复制第三方项目源码。
内置 HTTP 请求字段按 OpenAI 官方参考核对；JSON 模式后仍做本地 schema 校验。

没有增加 affection/trust/dependency 分数，没有按天过期的“情绪真值”，也没有自动改写角色人设。
关系叙事生成、完整关系时间轴产品界面、后台解释 worker 和全自动共指消歧不属于本批完成项。

## 用户可以实际感受到的变化

- 宿主只交普通消息、用户/角色范围、授权状态和投递键，即可得到原文 ID、候选与回答上下文。
- 模型挂了或当前消息太长，也不再把“没抽出来”变成“没保存过”。
- “团子 / 小团”有当前原文证据且唯一时能沿用人物 ID；两个“小王”不强行猜成一个。
- “面试 → 电话 → 拒绝”可沿现有 Episode 归属继续；放错的一句话可以移出，原文不变。
- 一条消息重投会复用已成功的解释；用户已经换话题时，旧响应上下文会被标成过时。
- 不因为启用解释器就要求用户每轮确认，也不会凭模型提案直接晋升用户长期状态。

注意：模型产出的普通候选仍不等于激活的 Current Truth。自动化减少的是宿主结构化接入工作，
不是取消证据与晋升边界。原始回合及其检索键仍支持未晋升小事的证据回查。

## 集中验证结果

依照要求先完成本批代码和场景用例，再集中运行验证。

| 检查 | 结果 |
|---|---|
| 完整 pytest 回归 | 242 passed，无失败、跳过或 xfail |
| 相对 0.7.4 基线 | 保留 199 项基线，新增 43 个参数化后用例 |
| 全项目语句覆盖率 | 5706 / 6392，89.27% |
| process_service 覆盖率 | 94% |
| HTTP interpreter 覆盖率 | 96% |
| entity_resolution 覆盖率 | 94% |
| turn_layers 覆盖率 | 100% |
| Ruff 与格式检查 | 通过 |
| strict mypy | 42 个源文件通过 |
| 魔法数字 AST 门禁 | 通过；不等于已完成数据校准 |
| 依赖一致性 | uv pip check 通过 |
| 源码包及 wheel 构建 | 通过 |
| 两种包的独立环境安装 | 通过，均只安装运行依赖 |
| 安装后的真实 CLI / HTTP | init、serve、鉴权、process、interpretation、recall、detach、规则直达通过 |
| 数据库检查 | schema 8，integrity_check 为 ok |
| Git whitespace 检查 | 通过 |

环境：Linux x86_64、Python 3.12.13。最终完整回归约 9.25 秒；这只是当前测试执行时长，
不是产品检索延迟、真实模型响应速度或规模基准。

存在 1 条上游 Starlette TestClient 关于 httpx 的弃用警告，不影响本轮结果。
没有隐藏 warning、禁用失败用例或放宽原有断言来获得通过。

上次留存的本地虚拟环境 Python 链接和检查二进制已失效，因此另建验证环境，没有覆盖旧环境。
旧 mypy 增量缓存也导致内部错误；使用独立缓存和非增量检查后正常通过。

## 验证覆盖的实际错误场景

- 用户、AI、第三人主体以及未知目录 ID；AI 旧输出不能转成用户事实。
- 新加坡/洛杉矶日期语义基线；解释器拿到明确 calendar_timezone。
- 精确“先听我说”、自然变体、混合纠错语句、未完成事项结果补全。
- 重复投递、同时投递同一消息、显式失败重试，不产生重复候选。
- 超预算长消息、裁掉过长历史、输出截断、不合法 JSON、拒绝输出、工具调用形状、HTTP 错误。
- 本地真实 HTTP stub 的完整请求/响应协议、usage、无隐式重试、重定向拒绝和响应大小上限。
- 同名不合并、别名必须出现在证据中、遗忘早期别名后不从后续记录复活。
- 跨关系/现实层过滤，默认排除敏感上下文，模型读取前已经完成原文持久化。
- 三天不同 conversation 的面试进展沿一个 Episode 延续，detach 及旧 revision 拒绝。
- 用户中途发新消息、模型返回前原文被遗忘，旧结果不重新激活或成为可直接发送的上下文。
- FTS 与 SQLite 语义检索采用一致的现实层过滤。

保留的 conversation replay 是 20 个场景 × 32 条消息，共 640 条合成聊天。
本轮还加入了统一入口的脚本化场景；校验的是协议、候选和最终注入证据。
这些不是由真实用户产生的聊天，也没有真实 LLM 生成回答后再评分。

## 首轮发现并修复的问题

首轮可核对输出为 238 passed、1 failed。现实层过滤一度使用“第一条 SpeechSpan 的层级”
判断整句，导致“用户自述 + 后半句引用”把用户自述一起过滤掉。

修复后先采用明确的整回合层级；对旧回合，只有同一非现实层的片段完整覆盖全文时，
才把整回合判为该层。部分引用仍保留用户自己的直接表达，原有引用屏蔽继续生效。
同时补充多片段覆盖、片段空隙、混合层级和词法/语义通道一致性检查。

没有通过删除这个旧测试掩盖回归。

## 魔法数字与成本边界

新增资源预算均有名称、配置入口、用途和原型身份，登记于 MAGIC_NUMBERS.md。
没有把候选分数伪装成概率，也没有把时间衰减当成感情失效。

- 默认模型调用关闭；精确指令可不调用模型。
- 一次 process 最多尝试调用一次解释器。缺密钥等本地失败不一定发生 HTTP 请求。
- model_usage 为 provider 返回值；缺失时为 null，不虚报零消耗。
- 预检估计不等于计费：provider 的消息封装、模型 tokenizer 和自定义额外 prompt 可能不同。
- 超长回合默认检索只能使用接口长度内的查询前缀，会明确返回该限制；原文保持完整。
- 多进程/断电后的远端计费不保证 exactly-once；没有假装单机锁是分布式队列。
- 这些上限未经 held-out 数据或真实设备 SLO 校准，production_eligible 仍为 false。

## 仍然不能声称已解决

1. 真实模型对方言、反话、人物共指、玩笑与计划的可靠识别，尚无真实效果数据。
2. 原始回合默认仍精确 conversation 召回；跨会话完整事件需经 episode 接口取证。
3. 实体目录是现有 JSON 证据派生，不是 100M 级实体/向量索引。
4. 原文静态加密、旧备份恢复后删除证明、100M 容量与故障测试仍是既有阻断项。
5. 不生成最终聊天回复、不发送通知、不调度提醒，不替代宿主发送前的 Policy Gate。
6. 模拟 provider 和固定提案测试不能证明真实陪伴体验，也不能证明真实 token 费用或响应时延。

## 接入与复验

详见 [INTEGRATION_0.7.5.md](INTEGRATION_0.7.5.md)，示例位于 examples/process_chat_turn.py。
保留的 tests/smoke_installed.py 可在独立安装环境下运行真实 CLI / HTTP 验证。

```bash
uv venv .venv-check
uv pip install --python .venv-check/bin/python -e '.[dev]'
.venv-check/bin/ruff check companion_memoryos tests examples
.venv-check/bin/ruff format --check companion_memoryos tests examples
.venv-check/bin/python -m mypy --no-incremental companion_memoryos
.venv-check/bin/python -m pytest --cov=companion_memoryos
uv build
```

本报告记录本批实现与集中验证结果，代码同步以仓库提交记录为准。
本批尚未进行真实模型调用或真人试用；代码上传不代表正式生产发布或包索引发布。
