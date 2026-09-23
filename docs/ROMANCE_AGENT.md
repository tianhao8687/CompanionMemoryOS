# 心隅 · 人机恋 Agent

心隅是本项目上的可运行应用：浏览器聊天 → `CompanionAgent` → 人格、关系、经历、
当前处境与 MemoryOS 召回 → 离线演示或模型 API → 本地对话账本。上下文由已有记忆层组合，
没有另建一套与原项目脱节的聊天记忆。

应用现已加入有界 Loop、MCP 工具、持久化定时任务和受限安卓 / 个人微信桥接，
入口为「能力与定时」。配置、使用范围与设备连接步骤见 [Agent 工具说明](AGENT_TOOLS.md)。

2026-09-23 新增自然候选记忆、事件关心、审批续跑、微信文本渠道和流式输出。
默认离线，不调用真实 DeepSeek。完整流程及更新后的架构见 [功能说明](FUNCTIONAL_COMPANION.md)。

## 启动

需要 Python 3.12 或更新版本。Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m companion_agent.app
```

或在安装后使用 `companion-romance`。仓库提供 `start-romance.ps1`，复用 `.venv`：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-romance.ps1
# 换端口
powershell -ExecutionPolicy Bypass -File .\start-romance.ps1 -Port 8766
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m companion_agent.app
```

访问 `http://127.0.0.1:8765`。服务仅监听本机；一个进程服务一个用户与一个伴侣，
支持多段对话。默认数据目录 `.agent-data/romance`，可使用 `--data-dir` 指定其他目录。
原来的 MemoryOS CLI/API 与 `companion-agent` 仍可独立使用。

## 第一次使用

1. 点击「开始设置」，填写角色名字、你的称呼，选择温柔、俏皮或沉稳风格。
2. 按需要勾选「以恋人设定与 AI 相处」。不勾选时采用普通陪伴身份；初次确认恋人
   身份不会虚构熟悉度和共同往事。聊天中的新边界、关系调整仍由原关系模型处理。
3. 选择“离线演示”即可先试用，无需 Key。以后选择“API 模型”时再配置自己的服务。
4. 明确选择本地保存授权与所选模式处理消息的授权；两项均同意才能聊天。
5. “保存并测试连接”在离线模式验证本地流程；只有 API 模式才发出真实、可能计费的
   连接测试请求。它不写成共同经历；“保存，回到聊天”只保存设置。

聊天支持 Enter 发送、Shift+Enter 换行和中文输入法。API 模式支持真实文字流，完成后
才写入历史；离线演示直接返回完整回复。失败时保留用户消息，可点击重试。
重复请求复用同一消息 ID；已成功请求不会再次调用模型。

新建对话保留关系与可跨会话使用的记忆；各段聊天记录独立，普通原文召回遵循原项目
的作用域限制。历史可向前分页，服务重启后仍可恢复。「记忆手札」展示已生效记忆、
近期状态、边界和经历，不把候选推断当作确定事实。导出包含该应用用户的对话与记忆，
不包含 API Key。手札提供已生效记忆的查看、更正、遗忘和事件跟进管理，不出现逐条确认流程。

明确说「以后叫我小雨」会保存可跨对话使用的称呼，新称呼会替换旧版本；
「记住：我喜欢白色郁金香」把原话连同证据存入手札。明确的日常偏好会自动生效，
无需用户确认；“我现在不喜欢咖啡了”自动更新，“忘掉咖啡的喜好”直接停用各版本并
阻止旧来源再次进入回复上下文。“以后先听我讲”等明确反馈可更新相处方式。引述、
假设和含糊情绪不会自动升级为长期事实。API 模式可额外开启已有模型提取器，原文
能直接支撑的高置信度普通偏好自动采用，其余仅保留内部候选，不打断用户聊天。

## DeepSeek 配置

以下配置仅在手动选择 API 模式后生效；本轮没有真实调用。

也可以在启动服务的同一终端提供环境变量：

```powershell
$env:DEEPSEEK_API_KEY = "在本机填入你的 Key"
$env:DEEPSEEK_MODEL = "deepseek-flash"
.\.venv\Scripts\python.exe -m companion_agent.app
```

页面输入的 Key 只存在服务进程内存中；重启后要重填。环境变量由服务进程读取。
不要在聊天、提交记录或源代码中放真实 Key。本应用不自动读取 `.env`。

默认地址为 `https://api.deepseek.com`，实际请求路径是 `/chat/completions`。
根据 [DeepSeek 官方文档](https://api-docs.deepseek.com/)（2026-09-22 核对），
默认模型采用 `deepseek-flash`，也可选择 `deepseek-v4-pro` 或填写账户实际可用的模型。
旧接口别名 `deepseek-chat` / `deepseek-reasoner` 的可用性由服务商决定；适配器按别名
所代表的模式处理，不额外发送 `thinking`。现代模型支持可选思考模式。

请求采用 `max_tokens`，普通模式发送温度，思考模式不发送温度；仅保存最终 `content`，
不显示或持久保存 `reasoning_content`。默认超时 120 秒，无自动付费重试；鉴权失败、
余额不足、限流、超时和不完整输出都有明确错误提示。

兼容服务可在高级设置修改 API 地址（不包含 `/chat/completions`），远程地址必须使用
HTTPS。本机 HTTP 仅用于本地服务/测试。改地址时需重新填写该服务的 Key，重启后
不会把官方服务的环境变量 Key 自动发送给已保存的其他地址。若要使用环境变量配置
兼容端点，启动前同时设置 `DEEPSEEK_BASE_URL` 与该端点的 `DEEPSEEK_API_KEY`。
已有设置优先于默认模型/地址环境变量。

原命令行 Agent 也新增了 DeepSeek 预设：

```powershell
.\.venv\Scripts\python.exe -m companion_agent --data-dir .agent-data/cli `
  --provider deepseek --identity romantic_partner --allow-model
```

Python 使用方式：

```python
from companion_agent import CompanionAgent, load_persona
from companion_agent.deepseek import DeepSeekConfig, DeepSeekLLM
from companion_agent.semantics import RelationshipIdentityType

# memory 是原项目的 CompanionMemoryService。
agent = CompanionAgent(
    memory,
    load_persona(),
    DeepSeekLLM(DeepSeekConfig(model="deepseek-flash")),
    initial_relationship_identity=RelationshipIdentityType.ROMANTIC_PARTNER,
)
# agent.chat(ProcessTurnRequest(...))；仍需显式提供保存与模型调用 consent。
```

## 本地 Web API

访问首页会获得 HttpOnly、SameSite=Strict 会话 Cookie。除健康检查外 API 都要求该
Cookie；写入请求还需 `X-Companion-Client: local-web`，有 Origin 时必须与本地来源一致。
页面不加载外部脚本、字体或分析 SDK。应用拒绝其他 Host 和跨站请求。

| 接口 | 用途 |
| --- | --- |
| `GET /api/health` | 本地服务健康检查，不调用模型 |
| `GET /api/bootstrap` | 配置状态与历史对话列表，不返回 Key |
| `PUT /api/settings` | 保存角色与非秘密配置，Key 只存内存 |
| `POST /api/connection` | 一次真实模型连接测试 |
| `POST /api/conversations` | 新建对话 |
| `GET /api/conversations/{id}/messages?before=序号&limit=80` | 分页读取聊天历史 |
| `POST /api/chat` | `conversation_id`、`request_id`、`content`，幂等聊天 |
| `GET /api/memories/{id}` | 本段对话可用的记忆与关系状态 |
| `GET /api/export` | 导出当前应用用户的本地记录 |

多次并发发送或生成期间修改设置会返回 busy；未完成的回复不写成已完成的对话。
当前为单进程本机应用，不提供公网多用户部署或系统推送。定时提醒在应用内送达，
现实操作通过已配置并获授权的 MCP 工具执行，详见 [工具说明](AGENT_TOOLS.md)。

## 验证

功能、界面、说明与测试用例整批实现后，执行以下集中检查：

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe companion_memoryos companion_agent
.\.venv\Scripts\python.exe -m pytest
```

`test_deepseek.py` 使用真实本地 HTTP 服务验证请求协议与错误处理，
`test_romance_app.py` 覆盖聊天、记忆、重启、重试、作用域、并发、授权与秘密保护。
它们使用可控的模型替身，不代表验证了真实模型的浪漫表达质量。

真实模型测试需显式启用，会消耗 API 额度：

```powershell
$env:DEEPSEEK_API_KEY = "在本机填入你的 Key"
$env:RUN_DEEPSEEK_LIVE = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_deepseek_live.py -q
```

没有 Key 时该项跳过。实际执行结果见 [集中验证记录](ROMANCE_VALIDATION.md)。
