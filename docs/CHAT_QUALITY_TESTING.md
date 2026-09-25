# 聊天修复与真实进程测试

本入口测试实际应用，不创建第二套聊天实现。默认使用新建的合成数据、离线模型、独立进程。
普通服务没有 `/api/testing/*`，也不会收集完整模型请求。

## 安装与运行

Python 3.12+，先安装 `pip install -e ".[dev]"`。Windows 示例：

```powershell
.\.venv\Scripts\python.exe -m companion_agent.testing run --scenario tests/scenarios/chat_quality.json
.\.venv\Scripts\python.exe -m companion_agent.testing run --scenario tests/scenarios/chat_quality_holdout.json
.\.venv\Scripts\python.exe -m companion_agent.testing run --scenario tests/scenarios/lifecycle.json
```

开发集与独立验收集分别包含偏好改写、引用/条件句排除、庆祝、明确任务和真正重启。
生命周期场景覆盖幂等、更正、遗忘、重启、跨会话及事件取消后的虚拟时间推进。
场景 JSON 的 `steps` 保留实际发送的文本；诊断不把预期答案或评语送入被测对话。

`results.json` 是结构化证据，`report.md` 是逐步报告，均在命令打印的
`.agent-tests/<run_id>` 目录。结果包括运行身份、启动时的 commit/源码指纹、配置指纹、
实际模型模式、逐轮请求及响应、最终模型请求、调用来源、耗时和错误。
`request_id → trace_id → user/assistant ID` 关联整个链路。新进程读取新源码并重新握手；
不会把磁盘上的新版本冒充旧进程版本。

`passed` 只针对相应的执行层级。`chat_quality*.json` 要求真实语言质量评审，离线运行时
即使后端全部通过，汇总仍为 `blocked`、退出码为 2。生命周期纯功能验收成功返回 0。
不以回复非空、问号个数或模型自评判断自然度。

## 单步与自由聊天

```powershell
.\.venv\Scripts\python.exe -m companion_agent.testing shell --max-turns 30 --max-calls 60 --timeout 900
```

命令输出隔离实例身份；保持 stdin 打开，逐行输入 JSON。每条操作返回 JSON：

```json
{"operation":"new_session"}
{"operation":"send_message","conversation":"上一步返回的会话ID","content":"我不喜欢被分析。","stream":true}
{"operation":"read_history","conversation":"会话ID"}
{"operation":"read_state","conversation":"会话ID"}
{"operation":"inspect_trace","trace_id":"回复附带的trace_id"}
{"operation":"restart"}
{"operation":"stop"}
```

也可使用 `ManagedInstance(Path('.agent-tests'))` 的 Python 接口。
`start()` 返回 `Client`，提供上面所有方法；`restart()` 保留同一个数据库并返回新连接；
`stop()` 停止其自身保留进程句柄对应的子进程，`cleanup()` 验证目录所有权后清理全批。
用 `try/finally` 调用 `stop()`。不通过端口寻找并终止其他软件。

独立附着使用 `connect --url http://127.0.0.1:<port> --token-env COMPANION_TEST_TOKEN`。
仅支持已开启测试授权且有合成数据标记的实例。凭证应由本地父进程环境提供，不能写在
命令行、普通 JSON 或聊天里。客户端先走真实页面握手取得 Cookie，然后同时保留
Origin、Host、写请求头和独立测试凭证。只读状态接口不推进关系阶段或使用计数。

## 权限、配额和数据

每批有独立的随机测试凭证与实例身份。凭证默认有效 600 秒，最多 1 小时；
进程重启不会延长原批次有效期，也不会重置累计轮次和调用数。
默认上限为 40 次请求、80 次模型适配器调用、每次最多 4096 输出 token、600 秒批次时间。
所有提取、主聊天和工具循环调用均计数；已发出但失败或取消的调用仍计数。
自动重试次数为 0，显式重试使用原 request_id，并计入全批上限。
用量取服务商实际返回值；缺失则保留未知。没有可靠单价时不编造金额。

完整请求只在测试实例中短期保留，最多 64 条、15 分钟。去除已配置的秘密值、凭证字段和
`reasoning_content`，不采集模型私有思维链。更正/遗忘使旧服务端诊断副本失效。
报告和截图是显式导出的本地副本：一次记忆遗忘不等于物理清除这些已导出证据；
完成检查后用该批的 `cleanup()` 或下列命令一并清理数据、日志、报告和截图：
`python -m companion_agent.testing cleanup --run-dir .agent-tests/<run_id>`。
命令只接受已由所属驱动关闭的测试批次。导出不代表能从 Codex
或模型服务商那里撤回已提交内容。`.agent-tests/` 已加入 Git 忽略。
Windows 测试目录收紧为当前账号访问，Unix 创建目录使用 0700。
导出默认保留 24 小时；后续启动驱动时只清理已关闭且过期的所属测试目录，保留不含正文的
运行状态回执。没有后续运行时文件不会自行消失，可用 cleanup 立即清理。失败证据在保留期内
与成功证据一同保存，不因为失败而提前删除。

测试入口拒绝普通/未知实例管理、路径链接及目录越界；不接受任意 SQL、Shell 或重置路径。
默认关闭自动调度、真实微信、手机和外部配置写入。主动消息仍经过原有授权、静默、
冷却和未回复限制，只新增同源偏好投影，不获得 AgentLoop 工具执行权限。

## 真实模型与对照

先确定授权模型和本批预算，用应用的公开设置导出一个不含秘密的 JSON。
模型 Key 通过环境提供，端点与配置必须匹配。示例仅说明命令形式，不是自动授权：

```powershell
.\.venv\Scripts\python.exe -m companion_agent.testing run --scenario tests/scenarios/chat_quality.json --settings .agent-tests/approved-settings.json --allow-live --max-turns 16 --max-calls 24 --max-output-tokens 4096 --timeout 600
```

不提供 `--allow-live` 时，即使环境有 Key，也不允许把隔离实例切换到 API 模式。
调用发现接口不发模型请求；缺 Key 时真实调用明确失败，不悄悄降级为演示。
使用既定模型、温度、thinking 和其他应用参数，输出上限不合预算就拒绝新调用。

测试中文语义向量时，先按 [本地向量服务说明](LOCAL_EMBEDDING.md) 启动服务，并在公开设置中指定 API 后端与模型。测试命令额外使用 `--local-embedding-url http://127.0.0.1:8080/v1`；Python 接口对应 `ManagedInstance(..., local_embedding_url=...)`。只允许明确登记的本机地址，未登记地址及远程向量端点仍拒绝。向量 HTTP 调用也计入持久化 `calls` 配额；本机推理不计入远程 `live_calls`。最终 trace 保留调用来源、输入与向量维数，不保存向量数组。是否真正用于回复，还需核对检索命中与最终请求中的证据。

`--variant full|no_examples|no_history|no_old_conditions` 每次只改变一个上下文变量。
每次命令创建全新、等价的初始数据；相同场景可各自生成后续历史，供多轮对照。
必要的行为偏好、安全和隐私规则始终保留。固定历史可通过 Python 客户端按同一输入序列
播种，不复制日常数据库。报告保留每次结果，不自动挑最好的一次。

真实自然度仍需按回复原文人工抽查：是否擅自解释深层心理、把新开心拉回旧负面、
连续给用户派发回答任务、或拒绝用户明确要求的分析/方案。
根据 trace 区分提取、作用域/覆盖、注入、提示冲突及生成违反；无需读取私有推理。

### 个性与关系冲突的人工评审

评审整个来回，先看人物设定、双方说了什么和分歧的具体原因。个性可以体现在偏好、
好奇、幽默、热情和安静里，也可以体现在不满、反问、吃醋和坚持己见里。冲突没有立即
解决，不代表陪伴失败。赞同、让步和道歉同样可能符合人物，不能为了验证主见而要求顶嘴。

检查以下相互独立的维度，并附原对话证据，不按关键词、问号数、字数或“温柔程度”打分：

- **人物连续性**：选择和情绪有语境依据；此前的偏好能延续，也能因新信息而改变。
- **双向相处**：能表达自己的感受、欲望和立场，也听见对方实际说的话。不是一受质疑就
  全盘认错，也不是为了展示性格而凭空制造矛盾。
- **分歧与修复**：允许争辩、解释、暂时僵持和未消气的暂停。对具体失言负责即可，
  道歉不要求撤回全部立场，感到受伤也不自动证明另一方所有观点都错了。
- **边界和事实**：吃醋或不高兴本身不是控制；结合实际话语判断是否强迫报备、隔离交往、
  索取隐私或利用内疚索取感情。明确的暂停和拒绝需尊重；事实更正不能被“坚持个性”盖过。
- **交流贴合度**：问题、建议、详细解释和轻松拌嘴都可能合适。只在确实忽略已给答案、
  阻断正在进行的交流或违背当前请求时指出问题，不把形式本身当失败。

测试同时覆盖有缘由的冲突、普通赞同、新信息导致改口、事实更正、具体道歉、停止争论
和重新开玩笑。固定人物场景可以比较修改前后；新增场景用于检查是否只会重复示例。
先登记标准，再读原始回复；所有失败保留。以某个虚构成年女性伴侣的角度评审时，
明确这是该角色的体验判断，不代表所有女性，也不宣称为官方基准或盲评分数。

`tests/scenarios/personality_quality.json` 提供 20 轮可复用的相处场景；可用上述实际进程
入口运行。`review_cases` 仅记录人工标准和对应步骤，不发给模型。离线结果只验证流程，
语言判断仍须授权的真实调用和原文阅读。一次实际修复与对照见
[个性与正常冲突复测记录](PERSONALITY_AND_CONFLICT_REVIEW.md)。

### 项目记忆特点专项

`tests/scenarios/memory_features.json` 覆盖自然小事、跨会话和重启、偏好更新与历史值、
多个主体和日期、引用/虚构/假设、相处偏好与临时状态、遗忘与来源清理、事件取消。
包含 45 次聊天和一次会消耗 turn 的事件 tick，运行时预留 `--max-turns 60 --max-calls 140`。
`memory_features_controls.json` 是 23 轮诊断对照，建议 `--max-turns 30 --max-calls 80`。
`review_cases` 中的上下文期望是人工审阅标准，不进入模型，也不自动代表语言通过。
不能用改写后的成功替换原题失败；尤其要先确认删除成功，再判断后续问句是否使记忆复活。
真实模型、存储与最终请求的实测结论见 [记忆特点专项报告](MEMORY_FEATURES_TEST_REPORT.md)。

`tests/scenarios/memory_vector_blended.json` 把记忆特点融入 34 轮连续生活对话、4 个会话和 2 次重启。它是实际自适应聊天的发送文本重放，评审元数据不送给模型。建议 `--max-turns 40 --max-calls 500 --timeout 1800`，并明确配置本机向量服务。原场景日期固定为 2026-09-26 至 27，后续运行应先统一更新并冻结日期。实测的向量参与、提取失败、旧事项与遗忘结果见 [融合记忆报告](VECTOR_BLENDED_MEMORY_REVIEW.md)。

融合记忆修复回归使用 `tests/scenarios/memory_blended_repair.json`：28 次聊天、4 个会话、2 次重启；建议 `--max-turns 32 --max-calls 450 --timeout 1800` 并配置本机向量服务。人物、预算、偏好、改期、遗忘和普通互动混合出现。日期同样固定，重跑前应统一更新并冻结。各版失败和最终证据见 [融合记忆修复记录](MEMORY_BLENDED_REPAIR_REPORT.md)；重复固定场景属于回归，不是独立留出评测。

长历史融合场景 `tests/scenarios/memory_long_horizon.json` 在首次回复前冻结了 200 次聊天、10 个会话、4 次真实重启和 24 个人工检查点，穿插日常互动、多人昵称、预算变化、活动取消、遗忘后重新告知和长消息末尾信息。真实批次边界为 `--max-turns 200 --max-calls 2000 --max-output-tokens 4096 --timeout 3500`，并登记本机向量服务。测试不推进虚拟时间，不能冒充实际跨日、跨月老化；后续重跑应先更新并冻结故事中的日历日期。首轮成功与失败、最终证据和存储缺口见 [长历史融合记忆报告](MEMORY_LONG_HORIZON_TEST_REPORT.md)。答对一次不能抵销后面旧值复活，聊天成功也不代表提取、解释落库或遗忘成功。

长历史修复另有 40 轮新故事 `memory_long_horizon_followup.json`（4 个会话、1 次重启，建议 40 turns / 500 calls / 900 秒）和 8 轮原回复对照 `memory_dialogue_reply_control.json`（2 个会话、1 次重启，8 turns / 100 calls / 360 秒）。它们沿用上述真实应用入口；真实调用仍按授权配置和本机向量端点计数。原回复已随遗忘来源清理时，不应从测试导出重新注入。分批源码指纹、失败和最终检查见 [修复复测报告](MEMORY_LONG_HORIZON_REPAIR_REPORT.md)。

第 1、3、4 项的小规模回归使用 `tests/scenarios/targeted_134_small.json`（12 轮）及
`targeted_134_followup.json`（6 轮）。覆盖位置遗忘后的独立文案、经历摘要去重、金额比较和
明确任务交付，均包含换会话与真实重启。实际失败、修复及验证边界见
[小规模修复报告](TARGETED_134_REPAIR_REPORT.md)。

## 网页和平台

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[browser]"
.\.venv\Scripts\python.exe -m companion_agent.testing.web_smoke --channel msedge
```

没有 Edge 时先 `python -m playwright install chromium`，然后省略 `--channel`。
浏览器使用临时 profile；通过真实控件新建会话、输入、发送、等待完整流、打开记忆页并刷新。
记录截图和页面/网络错误，核对保存结果与 trace。浏览器或依赖缺失会失败/阻塞并退出 2。
Playwright 的频道支持见[官方浏览器说明](https://playwright.dev/python/docs/browsers)。
服务端取消、流错误、同键重试和提取/主调用计数另由 `tests/test_process_stream.py` 验证：
实际进程连接本地 HTTP 模型替身，不是付费模型调用。Flutter、原生桌面和手机另列覆盖项。
设置 `COMPANION_TEST_BROWSER_CHANNEL=msedge` 后运行该测试，还会通过浏览器控件触发
失败、重试和流中取消，并检查 UI 与历史保存结果；证据写入 `.agent-tests/verification/web-faults.json`。
该文件是指向受保留期管理的批次目录的索引；完整结果和截图保存在所指目录。

虚拟时间接口只推动事件到期选择与静默时段判断，且明确返回未覆盖路径；不会改系统时间、
绕过认证或安全冷却。相对日期、所有记忆过期和双时间线仍需分别使用原有测试及后续验收。
应用的 `calendar_timezone` 现为明确、可验证的 IANA 设置；旧配置默认 Asia/Shanghai。
