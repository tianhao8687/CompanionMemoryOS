# 高 Star 开源陪伴项目与「心隅」对照分析

核对日期：2026-09-22。本次按用户明确的“成熟开源项目、Star 较多”要求，主样本选择超过 5000 Star 的五个官方仓库，并检查发布记录、默认分支源码和文档。Star 数据直接来自 GitHub API，抓取时间为北京时间 21:15；数值会变化。没有运行这些外部项目，也没有测量它们的真实模型质量。架构判断来自所检查的代码路径，不能视为完整代码审计。

**核心判断：以 MaiBot 作为陪伴行为和记忆集成的主要参照，以 AstrBot 作为工具与消息渠道的主要参照，再从 AIRI / Open-LLM-VTuber 借鉴语音和角色表现。心隅已有可保留的 MemoryOS 与受限执行基础，当前最需要补齐自动记忆、持续陪伴调度与实际消息渠道。**

成熟陪伴体验需要连续完成五件事：理解这一刻的需要、记住值得留下的事情、维持同一个角色、选择合适的联系时机、根据后续反馈调整相处方式。MCP 和手机控制可以扩展行动能力，但需要接进这条连续流程。

## 高 Star 开源项目对照

| 项目 | Star | 定位与已核对机制 | 发布与成熟度判断 |
| --- | ---: | --- | --- |
| [AIRI](https://github.com/moeru-ai/airi) | 49,329 | 虚拟伴侣平台；语音、Live2D / VRM、桌面与 Web、多种互动集成；源码中已有 MCP 桥接与 computer-use 服务 | 最近发布标签 `v0.12.0-beta.5`，2026-08-29；默认分支 09-22 有提交。社区关注度高，仍处快速演进阶段，README 的 Alaya 记忆部分标为 WIP。 |
| [AstrBot](https://github.com/AstrBotDevs/AstrBot) | 40,839 | 多平台 Agent 框架；工具循环、MCP、插件、消息渠道和未来任务 | `v4.28.1`，2026-09-14；适合参考工程与渠道接入。主动 Agent 文档仍将该功能标为实验性。 |
| [SillyTavern](https://github.com/SillyTavern/SillyTavern) | 33,675 | 角色扮演与模型交互前端；角色卡、World Info、摘要、向量检索扩展和 TTS | `1.19.0`，2026-09-14；持续多年的发布与扩展生态，适合参考角色及上下文管理。自主行动不是其主要定位。 |
| [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) | 13,874 | 语音伴侣；ASR、LLM、TTS、打断、视觉与 Live2D；可替换 Agent 接口 | 最近正式发布 `v1.2.1`，2025-08-26；默认分支最新提交 2026-05-15。README 说明 v2 重写处于早期讨论规划，长期记忆功能暂时移除。需区分已有语音实现与下一代规划。 |
| [MaiBot / 麦麦](https://github.com/Mai-with-u/MaiBot) | 6,025 | 中文拟人聊天 Agent；回复时机、Planner、长期记忆、人物画像、插件和 MCP 模块 | `1.2.5`，2026-09-13；默认分支 09-22 有提交。最贴近陪伴行为目标，但许多设计面向群聊，需要适配一对一恋人关系。 |

这里没有把 Star 当作稳定性评分。SillyTavern、AstrBot 的发布与生态更适合评估工程成熟度；AIRI 的关注度很高，但仍应逐项区分可用功能、实验功能和路线图。Open-LLM-VTuber 需要额外考虑重构阶段与发布间隔。

发布依据：[AIRI](https://github.com/moeru-ai/airi/releases/tag/v0.12.0-beta.5)、[AstrBot](https://github.com/AstrBotDevs/AstrBot/releases/tag/v4.28.1)、[SillyTavern](https://github.com/SillyTavern/SillyTavern/releases/tag/1.19.0)、[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/releases/tag/v1.2.1)、[MaiBot](https://github.com/Mai-with-u/MaiBot/releases/tag/1.2.5)。Star 与源码快照保存在本地研究数据目录 `.agent-data/research/`。

## 从源码中值得借鉴的部分

**MaiBot：陪伴行为的首要参照。** `MessageTurnScheduler` 在进入 Planner 前处理回复必要性、频率、等待状态和退避；聊天循环按场景决定何时查询记忆。A_Memorix 已将向量与图谱召回、Episode、人物画像和管理工具组织成子系统。相较之下，心隅已有可信记忆的存储与校验基础，默认应用的自然语言抽取、自动向量生成和主动判断还没有形成完整日常路径。借鉴重点是接通运行链路，不宜直接照搬群聊中的跨会话游走行为。

源码依据：[调度器](https://github.com/Mai-with-u/MaiBot/blob/6c7ef47c592b5b383d119f330045ea24f3f5e32a/src/maisaka/turn_scheduler.py)、[聊天循环](https://github.com/Mai-with-u/MaiBot/blob/6c7ef47c592b5b383d119f330045ea24f3f5e32a/src/maisaka/chat_loop_service.py)、[A_Memorix](https://github.com/Mai-with-u/MaiBot/blob/6c7ef47c592b5b383d119f330045ea24f3f5e32a/src/A_memorix/README.md)。这些机制的存在不证明其中文情感理解一定优于当前配置的 DeepSeek。

**AstrBot：工具、调度与渠道的首要参照。** 工具 Runner 包含流式响应、停止请求、工具执行中追加消息等处理；FutureTask 会在未来唤醒 Agent 并反馈结果。心隅目前的定时任务执行固定通知或固定工具参数；可以参考它的事件唤醒与渠道反馈方式，继续保留现有权限和防重复执行机制。其主动推送支持范围按平台变化，文档没有把个人微信列进该功能的支持平台清单。

源码依据：[ToolLoopAgentRunner](https://github.com/AstrBotDevs/AstrBot/blob/95e98b8aed75d56713666eff39e31bafffd95426/astrbot/core/agent/runners/tool_loop_agent_runner.py)、[主动型能力](https://github.com/AstrBotDevs/AstrBot/blob/95e98b8aed75d56713666eff39e31bafffd95426/docs/zh/use/proactive-agent.md)、[MCP 接入](https://github.com/AstrBotDevs/AstrBot/blob/95e98b8aed75d56713666eff39e31bafffd95426/docs/zh/use/mcp.md)。

**微信路线需要更新。** AstrBot 当前已有 `weixin_oc` 适配器。按其官方项目文档，该通道通过扫码和长轮询接入个人微信，要求微信具备 ClawBot 插件，并列出 Android 8.0.69 / iOS 8.0.70 的最低版本条件。对心隅，可以优先评估它作为用户与伴侣聊天的入口；ADB 继续用于用户授权的手机界面操作。扫码通道不能据此推定能读取全部既有聊天、代发给任意好友，或支持所有主动推送场景；这些能力应独立验证。本次没有登录微信或发消息。[接入文档](https://github.com/AstrBotDevs/AstrBot/blob/master/docs/zh/platform/weixin_oc.md)、[适配器源码](https://github.com/AstrBotDevs/AstrBot/blob/95e98b8aed75d56713666eff39e31bafffd95426/astrbot/core/platform/sources/weixin_oc/weixin_oc_adapter.py)。

**AIRI：参考多端表现与能力桥接。** 已检查的调用路径将前端聊天流交给 core-agent，将 MCP 工具通过桥接接口连接到具体运行环境；插件平台设计文档还区分生命周期/权限控制与音频、视觉等高频数据。心隅可借鉴这种隔离，使手机操作、语音和角色表现都调用同一套记忆与关系服务。设计文档中的目标不等于全部实现，也不建议为了角色外观重写当前 Python 核心。

源码依据：[聊天流接入](https://github.com/moeru-ai/airi/blob/308ee2b3aa8587262aa7a458d5d68407cb5f2342/packages/stage-ui/src/stores/ai/chat-llm/llm.ts)、[MCP 桥接](https://github.com/moeru-ai/airi/blob/308ee2b3aa8587262aa7a458d5d68407cb5f2342/packages/stage-ui/src/stores/mcp-tool-bridge.ts)、[插件架构设计](https://github.com/moeru-ai/airi/blob/308ee2b3aa8587262aa7a458d5d68407cb5f2342/packages/plugin-sdk/docs/design/architecture.md)。

**Open-LLM-VTuber：参考语音链路与可替换 Agent。** TTS 管理器允许并行生成并按顺序发送；BasicMemoryAgent 处理中断时，用用户实际听到的内容修正聊天历史。心隅增加语音时，应让记忆中的“已说过”与实际播放保持一致，并能取消后续播报。它的基础聊天历史机制不能直接当作经过验证的长期关系记忆系统。

源码依据：[Agent 接口](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/agent/agents/agent_interface.py)、[打断与历史](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/agent/agents/basic_memory_agent.py)、[TTS 管理器](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber/blob/992309c0aa19845960228f880013d4685fde93b5/src/open_llm_vtuber/conversations/tts_manager.py)。

**SillyTavern：参考用户控制角色与上下文的方式。** World Info 按上下文启用相关设定，另有聊天摘要和向量扩展。心隅可以借鉴角色资料编辑、记忆校对和上下文预算控制，但应继续区分用户现实事实、角色设定与共同经历，避免任意世界书内容覆盖真实记忆。

依据：[World Info 文档](https://docs.sillytavern.app/usage/core-concepts/worldinfo/)、[摘要扩展](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/scripts/extensions/memory/index.js)、[向量扩展](https://github.com/SillyTavern/SillyTavern/blob/06bde939fb1e9c4c8d8641d810f0a916b5bce127/public/scripts/extensions/vectors/index.js)。

## 本项目与这些参照的关系

| 参照方向 | 对心隅的具体判断 |
| --- | --- |
| MaiBot 的陪伴调度与记忆 | 优先补齐自然记忆提取、检索、关系反馈及何时联系的持续流程。 |
| AstrBot 的运行与渠道 | 参考事件入口、MCP 生命周期、未来任务回流和微信适配；增强现有执行层。 |
| AIRI / Open-LLM-VTuber 的表现层 | 后续加入可打断语音、角色动作与多端入口，保持同一套关系记忆。 |
| SillyTavern 的角色控制 | 完善角色资料、示例对话、记忆更正和检索内容的可见性。 |

## 心隅当前的实际位置

以下判断来自默认 Web 应用的运行路径；底层库支持某个接口，不代表应用已经启用该能力。

| 维度 | 当前已有 | 实际缺口与影响 |
| --- | --- | --- |
| 记忆可信度 | 原文、来源证据、作用域、状态修订、现实与角色扮演区分、记忆使用记录 | 有实质基础，适合追查“为什么记成这样”；但不能据此推断真实召回质量领先竞品。 |
| 自然聊天形成记忆 | 原文账本、明确记忆指令、关系与状态规则；底层有可选语义抽取器 | 默认抽取器关闭。配置 DeepSeek 聊天 Key 不会自动启用它。普通表达能否稳定转成跨会话记忆，仍是关键缺口。 |
| 语义检索 | 底层有 SQLite 向量索引和接收向量的接口 | 当前 Web 路径没有生成、写入和查询 embedding 的完整接入。不能把存在 semantic 模块等同于已具备自动语义检索。 |
| 情绪与关系 | 当前状态、关系身份、边界、分歧修复、共同经历 | 本地结构化识别较多依赖关键词和规则。模型仍可能读懂语气，但系统能否持续保留含蓄表达的意义需要实测。 |
| 角色成长 | 基础人格内核、三个可选风格、自定义资料；关系和经历会变化 | 没有完整的角色反思更新机制。现阶段不能把关系记录增长等同于稳定、自然的个性成长。 |
| 主动陪伴 | MemoryOS 有主动联系判断与未完事项；应用有持久化调度器 | 两者尚未串成“发现值得关心的事 → 判断时机 → 生成贴合语境的消息 → 送达 → 记录反馈”。默认主动开关也关闭。 |
| 行动执行 | 有界 Loop、MCP、权限、操作账本、重复请求复用和结果不明时停止 | 待确认动作会结束本轮 Loop；用户确认后执行该动作并通知，但不会自动恢复原计划和后续对话。 |
| 安卓与微信 | ADB 桥接、应用和联系人范围限制、当前界面校验 | 当前是手机上已打开聊天的工具操作。没有后台收信、微信消息进入 Agent 的完整入口，也未完成真机联调。 |
| 日常体验 | 本机 Web 聊天、历史、记忆手札、通知与设置 | 没有语音输入/输出、真正的流式回复和手机推送；服务需要保持运行。记忆更正与遗忘能力也未完整放进界面。 |
| 质量证据 | 已有自动化测试、合成中文对话回放、模拟模型与 MCP 联调 | 当前验证记录为 563 passed、1 skipped。真实 DeepSeek 和真机尚未验证；这组结果不证明浪漫表达、人格一致性或多周相处效果。 |

代码依据：

- [应用装配与聊天入口](C:/Users/Administrator/Documents/ChatGPT/2/companion_agent/app.py:101)、[默认抽取配置](C:/Users/Administrator/Documents/ChatGPT/2/companion_memoryos/defaults.toml:70)、[向量索引](C:/Users/Administrator/Documents/ChatGPT/2/companion_memoryos/semantic_index.py:78)。
- [当前状态规则](C:/Users/Administrator/Documents/ChatGPT/2/companion_agent/current_state/evaluator.py:54)、[关系评估](C:/Users/Administrator/Documents/ChatGPT/2/companion_agent/relationship/evaluator.py:94)、[经历主题识别](C:/Users/Administrator/Documents/ChatGPT/2/companion_agent/experience/evaluator.py:46)、[人格装配](C:/Users/Administrator/Documents/ChatGPT/2/companion_agent/romance.py:81)。
- [主动联系判断](C:/Users/Administrator/Documents/ChatGPT/2/companion_memoryos/proactivity.py:9)、[调度执行](C:/Users/Administrator/Documents/ChatGPT/2/companion_agent/automation/scheduler.py:82)、[待确认时退出 Loop](C:/Users/Administrator/Documents/ChatGPT/2/companion_agent/automation/loop.py:172)、[确认后执行路径](C:/Users/Administrator/Documents/ChatGPT/2/companion_agent/automation/hub.py:278)。
- [非流式请求](C:/Users/Administrator/Documents/ChatGPT/2/companion_agent/llm.py:54)、[微信接入范围](C:/Users/Administrator/Documents/ChatGPT/2/docs/AGENT_TOOLS.md:103)、[界面记忆管理限制](C:/Users/Administrator/Documents/ChatGPT/2/docs/ROMANCE_AGENT.md:57)、[既有验证记录](C:/Users/Administrator/Documents/ChatGPT/2/docs/ROMANCE_VALIDATION.md:54)。本次为资料研究和代码审查，没有重新运行测试。

本地保存也不等于离线推理：聊天及被选入上下文的记忆、工具结果仍会发给所配置的模型服务。可控的数据和模型接入是项目方向，不能由此直接推断隐私保护强于所有商业服务。

## 最需要补上的连续流程

建议保留现有层次，连接两种不同的循环。

**陪伴循环**：聊天或事件到来 → 更新有证据的状态与记忆 → 判断此刻需要倾听、建议、一起办事还是保持安静 → 表达 → 接收反馈。用户离开后，只有合适的事件与已开启的联系偏好才触发下一轮。

**行动循环**：明确目标 → 计划下一步 → 检查权限 → 工具执行 → 核对结果 → 继续、等待确认或停止。等待确认应保存可恢复状态；确认后重新核对界面与条件，继续剩余任务，并把真实结果带回聊天。

两者共享关系、记忆和事件记录。定时器负责唤醒；陪伴循环决定值不值得联系以及说什么；行动循环决定怎样可靠地完成动作。这是建议目标，当前尚未完整实现。

用“我明天下午有面试，有点紧张”验收会比统计层数更有效。理想行为是先回应紧张，准确记下事件，按用户选择决定是否提醒；面试后在合适时机询问结果。如果用户随后说“已经取消了，先别问我”，系统应及时更新事实、撤销相关跟进。只增加一个定时任务，无法完成这整段相处过程。

## 建议推进顺序与验收

| 顺序 | 改动范围 | 可观察的验收结果 |
| --- | --- | --- |
| 第一轮：记忆与真实对话 | 接通已有语义抽取器；补齐 embedding 写入/查询；保留证据校验；提供记忆更正、遗忘入口；固定一个 DeepSeek 模型建立质量基线 | 自然表达的偏好在新会话和换一种说法后仍可被正确使用；新信息替代旧状态；不会把引用、玩笑或模型猜测写成事实。 |
| 第二轮：持续相处 | 在现有关系、经历、未完事项上增加有证据的反思更新；接通主动判断、事件调度与消息送达 | 用户反馈“少说教、先听我讲”能改变后续相处；事件取消后不再追问；未回应时降低主动联系；允许选择保持安静。 |
| 第三轮：完成行动与微信入口 | 保存与恢复等待确认的流程；评估并接入符合条件的微信扫码聊天通道；重新观察设备状态，完成一台指定安卓手机的受限操作链路 | 确认后继续剩余步骤；重启不会重复发送；无法确认结果时如实报告；微信入站消息进入同一关系与记忆。扫码聊天通道和 ADB 操作范围分别验证，主动推送另验。 |
| 第四轮：表达与可达性 | 流式文字、语音输入/输出、渠道一致的历史、后台运行与通知 | 文字与语音使用同一段关系记忆；用户无需一直守着电脑页面；测量首字延迟、完整响应延迟、失败率及模型调用成本。 |

每轮先完成实现，再集中验收，延续此前约定。质量评测应包含长间隔重逢、偏好更正、同名人物、隐含情绪、只想倾诉、分歧修复、亲密边界变化、事件取消和执行失败；同时记录检索是否正确、是否误用记忆、是否保持角色、回复是否自然、主动联系是否合时宜。已有合成回放可以复用，但要补真实模型输出与人工判断。

暂时不把角色商城、多角色社区、复杂 3D 形象排在前面。对当前“一个能长期相处、也能帮忙办事的伴侣”目标，优先证明连续相处的质量。也不急于训练专用模型：先通过真实样本区分问题来自模型、上下文还是记忆与行动流程，再决定是否需要训练。

**建议定位：一个记得共同经历、会调整相处方式、能在授权范围内参与日常事务的中文 AI 伴侣。** 当前最有价值的下一步，是让现有记忆、关系、主动判断与执行模块真正协同起来。
