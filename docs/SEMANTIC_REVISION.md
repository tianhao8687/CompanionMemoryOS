# v0.4.1 语义修复与表达策略精简

起点是 `8e24b81faef7f48df9f2901d148238f6675025e2`，2026-09-14 执行时远端 main 仍是该提交。
任务目录只有未产生提交的空 Git 仓库，没有用户未提交文件；拉取后在
`codex/semantic-dialogue-revision` 实施，未改动 main。

## 修复和精简

- 否定只作用于相应谓词；在分句之间保留第三方、转述与假设范围，时间前缀不再掩盖主体。
  问句、推测、未来意向和复杂双重否定不直接变成确定状态。肯定自述、真实抱怨和明确和解仍写入。
- Current State 与默认旧关系评估器共用冲突/修复候选生成逻辑。正常入口只更新一次；
  可选状态组件停用或失败时也使用相同语义。自定义评估器不能在有效 Current State 之后覆写其冲突槽。
  删除旧的“本轮倾诉”关系动态写入，保留 Current State 的有期限沟通要求。
- 可选解释器的话语标签需要当前直接证据支持，不能借一段无关的直接话语激活引用中的命令。
  模型建议不再被升级为持久的明确用户要求；未增加必需模型调用。
- 明确倾听跨窗口、重启延续；新任务或明确改为建议及时退出旧倾听，不要求用户先恢复情绪。
  不再仅凭问号认定任务。暂停话题按对象保存，重开面试不会顺带重开房租，事项完成也不释放引用边界。
- ResponseGoal 保留接口，编译为可组合的风格建议。去掉倾听枚举对角色背景的统一屏蔽和例子的熟悉度硬筛选；
  幽默由原 hard 风格标签改为 soft 偏好，主动要求笑话可覆盖旧低落/临时少开玩笑要求。
  hard/soft 在此是提示标签，原项目没有相应的输出拦截器。
- 只有明确距离边界/宿主显式上限决定距离；久未聊天和推断紧张不再自动令表达降温。
  长间隔可提供有来源的时间事实。熟悉度仍由真实历史决定，不是热情或亲密表达的解锁等级。
- 合并重复关系摘要和目标提示。关系与当前状态移到 user 级 JSON 证据；system 层保留应用规则、
  人格与使用权限。区分 `explicit_request`、`self_report` 和目标 `suggestion`，不把用户历史或模型猜测提权。
- 保留独立判断、真实来源、同意、删除、隔离、现实层、用户纠正和长期边界。
  称呼边界保留明确对象；普通处境可以按预算省略，明确要求放不下时取消计划并报错，不能静默丢失。
- 增加近期历史的来源过滤与助手依赖记录；来源被限制/删除时过滤直接回复和后续派生回复，
  发送前再次检查。旧 v0.4.0 助手的状态依赖可从现有状态事件审计恢复，缺依据则不使用该派生回复。

没有增加记忆库、后台任务、前端或模型自主工具循环。原 MemoryUsePlan 的证据权限、
OpenLoop 生命周期、关系身份与经历校验继续保留。

## 兼容、纠正与配置

`agent.chat`、`agent.prepare`、ResponseGoal、状态配置及数据库 schema 均保持兼容。
默认人格改为 0.1.2、Agent 元数据为 0.4.1；旧人格版本的种子仍保留。
`PreparedResponse.context_turn_ids` 和 `CompiledCurrentState.has_explicit_requests` 有兼容默认值。
`[CURRENT STATE]`、`[RELATIONSHIP CONTEXT]` 现在在 user 消息中，读取原始提示分段的宿主需调整位置。
关系时间间隔参数仍可用于提供时间事实，不再作为收紧表达距离的阈值。

无整库重算、清空或破坏性迁移。已有错误状态可以通过正常用户纠正恢复：

- “我不是难过，只是累”只撤回低落，保留疲惫和其他独立压力。
- “你记错了，我们没有吵架”记录有 `user_correction` 来源的撤回；不把它说成已经和解或更亲密。
- “你记错了，我还没原谅你”撤销错误的修复结论，重新保留未解决分歧。

没有新证据时不擅自改写旧记录。来源删除/受限只令相应证据不可用，不等于事实相反或冲突已解决。
无对象的旧引用暂停保留其原有范围；需要明确对象才能进行有针对性的更改。
临时状态组件不可用时按当前原话保守降级。若有效明确要求超过状态/总上下文预算，
宿主需提高相应预算；这类配置错误不会伪装成正常降级。

## 工程验证

环境为 Windows、Python 3.12.14；Ruff 0.16.7、mypy 1.20.2、pytest 8.4.2、tiktoken 0.14.0。
Ruff 固定到 0.16.7，统一本地与 CI 的 Markdown 代码块格式行为。

原基线本地重新运行：372 项通过，严格 mypy 覆盖两个包共 75 个源文件通过。
新建的首批 21 个成对回归在改代码前为 11 失败、10 通过，复现了误记和肯定表达漏记。
[原 CI job](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/34839922536/job/103962242535)
则是 lint 通过、格式失败、mypy/pytest 跳过，失败文件为 5 份 Markdown 文档，不能与本地测试混为一谈。

在已执行 `python -m pip install -e ".[dev]"` 的环境中，本轮验收命令：

```powershell
python -m ruff check .
python -m ruff format --check .
python -m mypy companion_memoryos companion_agent
python -m pytest --cov=companion_memoryos --cov=companion_agent --cov-report=term-missing
python -m pip check
python examples/current_state_replay.py --data-dir .agent-data/current-state-final
python -m companion_agent --data-dir .agent-data/cli-final --prepare "我很累，帮我修改自我介绍。"
python -m companion_agent --data-dir .agent-data/cli-final --current-state
python -m companion_agent --data-dir .agent-data/cli-disabled --no-current-state --prepare "你好。"
python -m pip wheel --no-deps . --wheel-dir .agent-data/wheels
```

最终结果、对照成本和远端 CI 记录见本页末尾“交付验证记录”。范围覆盖全仓格式/lint，
两个包的静态检查、全套测试及打包入口，未删除检查或缩小范围。
旧测试中只调整了提示承载位置、人格版本与不再成立的风格断言，来源、同意、隔离和明确要求的验收保留并补充。

## 对照回放与体验验证

`examples/revision_replay.py` 使用 13 组、35 轮相同输入，经过真实 `agent.chat`、持久化和主模型输入边界。
基线和修订版均为传输桩。示例是状态/提示行为对照，不能当作自然语言回复质量提升的证明。

| 场景 | 原版记录/控制 | 修订版 |
| --- | --- | --- |
| 没有打断，表示感谢 | 冲突 0.85，继续要求倾听 | 不建立冲突 |
| 有冲突后说不能原谅 | 冲突清为 0，误报修复 | 保留冲突和未解决事项 |
| 今天我朋友难过 | 用户名下新增低落 | 不写为用户状态 |
| 你刚才误解我，我很生气 | 漏记真实抱怨 | 记录有来源的分歧，明确和解后退出 |
| 引用别人说原谅、第三方和解 | 任务书这两个例句原版已正确 | 保留回归，增加跨句对象与意向反例 |
| 倾听后要求笑话/改介绍 | 旧倾听可继续占主导，低落硬风格仍在 | 当前任务优先；低落未被当成已恢复 |
| 久别热情问候 | 自动 cautious | open；明确保持距离的对照组仍 reserved |
| 暂停面试、暂停房租，再重开面试 | 两条暂停没有被识别为状态 | 只释放面试暂停，保留房租限制与压力 |

同一个脚本可以复制到基线检出目录后分别运行：

```powershell
python examples/revision_replay.py --output .agent-data/validation/replay.json --include-context
```

已授权模型可通过显式 `--live-config` 运行；此参数才会调用配置的主模型。
例如在本地建立 `main-model.json`（API 密钥只放环境变量）：

```json
{
  "base_url": "https://YOUR-HOST/v1",
  "model": "YOUR-MODEL",
  "api_key_env": "MAIN_LLM_API_KEY",
  "timeout_seconds": 60,
  "max_output_tokens": 1200
}
```

```powershell
python examples/revision_replay.py --live-config main-model.json --output .agent-data/validation/live.json --include-context
```

两次检出应使用相同模型、配置和服务端默认采样设置。内置适配器未增加温度/随机种子控制，
报告明确记录这一限制。脚本保存逐轮输出、上下文、延迟、调用与用量；完成实时调用也不自动标成体验验收通过。
需要逐例评审任务是否完成、明确要求是否尊重、自然度、错记/误引用及多余追问，并保留退化例子。

本次没有可用且已授权的主模型配置，**真实模型体验未验证**。
本地回放无主模型网络调用、无新增解释器调用，也没有评审模型总分。

## 剩余局限

规则仍是保守兜底，无法全面理解反话、复杂省略和任意话题名称；不确定内容留给主模型自然理解，
不因填档追问。未有新证据的历史误记不会自动重判；旧审计不足的派生回复可能被保守省略。
无对象的代词重开只处理唯一候选；MemoryOS 的独立引用禁令不能靠新话题自动解除。
来源依赖过滤增加本地查询成本，长期大库负载未测。未来可评估复用检索接口的只读按需记忆工具，
本轮没有实现，也未给主模型新增写库或外部操作权限。

## 交付验证记录

本地结果（2026-09-14）：全仓 lint、格式检查通过；严格 mypy 两个包共 75 个源文件通过；
**422 项测试通过，覆盖率 89%**，耗时 94.23 秒。两条既有警告来自 Starlette/httpx 和 AnyIO 弃用，
没有跳过失败测试。`pip check` 无依赖冲突；CLI prepare、状态查询和禁用开关运行成功。
旧连续回放的当前状态占用为 113、113、115、18 token。

wheel 构建成功，并以 `--no-deps --target .agent-data/wheel-installed` 安装；使用 `python -I`
检查两个包确实从安装目录导入，实际完成“先听我说 → 后续延续 → 两个办法”链路，
确认 MemoryOS schema 8、Current State schema 1。wheel SHA-256：
`bbbfc75d996cd2a8b381570dbf5d0b28dd36e4c23db65e8fece69840e68a9fc2`。

35 轮对照的逐轮记录和提示位置检查保存在
[validation/semantic_revision.json](validation/semantic_revision.json)。回放在提交前运行，
因此两侧 `commit_at_execution` 都记录起点；`runtime`、`persona` 和修订后的规范化源码摘要区分版本。
基线的 dirty 状态仅来自新增验收文件，运行代码尚未修改。

| 指标 | 基线 | 修订后 |
| --- | ---: | ---: |
| 每轮端到端延迟中位数 | 174.76 ms | 198.50 ms |
| 每轮端到端延迟 P95 | 230.19 ms | 295.52 ms |
| 主模型输入 token 中位数 | 1550 | 1679 |
| 主模型输入 token 最大值 | 1637 | 1799 |
| 主模型适配器调用 | 35 次传输桩 | 35 次传输桩 |
| 实际主模型网络/解释器调用 | 0 / 0 | 0 / 0 |

本组上下文中位数增加 129 token（约 8.3%），延迟中位数增加约 13.6%。
来源检查、边界承载和可组合风格提示有成本；这是同机代表性回放，受宿主负载影响，
不是受控性能基准，也没有证明自然度提升。没有把更短回复、更多测试或更少枚举当作验收结论。

远端使用本分支 push 触发的同一工作流，保留全仓检查并覆盖两个包；
[该修订分支的 CI 记录](https://github.com/tianhao8687/CompanionMemoryOS/actions?query=branch%3Acodex%2Fsemantic-dialogue-revision)
按提交 SHA 核对，具体运行链接随交付结果提供。
