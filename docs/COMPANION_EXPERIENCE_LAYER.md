# Companion Experience Layer（0.5，待集中验证）

这一层解决“记得之后怎么相处”，不以记忆条数、追问次数或消息数量作为效果指标。实现位于 `experience.py`，与检索评分、存储策略和实际聊天模型分开。

## 从用户感受看新增行为

| 用户的实际需求 | 内核提供的行为 | 仍由宿主负责 |
|---|---|---|
| “今天听我说就好” | `listen` 目标，先回应当前话语，旧经历默认不点名 | 从自然语言识别本轮目标，生成具体措辞 |
| “你别每次都提那件事” | 已发送证据使用账本；同会话重复回忆退回无声影响 | 正确报告实际发送；合理划分 conversation |
| “面试结束了” | 有上下文时才询问尚未结束的话题；问过后等待回复 | 识别事项、话题和结果，将其映射到同一 open loop |
| “不是那个杯子” | 对 memory/event/turn 统一记录错配，不要求先生成记忆卡 | 从最近回复引用中选择被纠正的对象 |
| “以后别主动提这个” | scope 内抑制再次引用，不篡改原始经历 | 区分“这次不是它”和“以后不提”，选择反馈范围 |
| “等等，我想说另一件事” | 原始用户回合提交时同步取消未发送拍；另有无正文打断接口 | 停止生成和撤销已排队的外部消息 |
| “那个幸运东西” | 原始回合多 key / 可选 embedding / episode 候选去重 | 生成并校验索引 key、向量与事件身份 |

## 记忆不必每次被说出来

`MemoryUsePlan` 对每项证据作独立决定：

| mode | 用法 |
|---|---|
| `silent_influence` | 影响理解、语气、建议，不主动说“你以前告诉过我” |
| `soft_reference` | 自然点到相关经历，保留恰当的不确定性 |
| `explicit_recall` | 用户确实在问往事，并且证据允许明确回忆 |
| `clarify` | 回忆问题确实依赖区分候选，问一个有用线索 |
| `suppress` | 本轮不使用、不暗示、不换个来源重新说出来 |

偏好、支持方式和关系背景通常无声影响回答。普通安慰场景里出现检索歧义，不会自动追加一个“请确认是哪次”的问题。用户明确问往事但证据不足时，生成 `memory_gap` 拍：只能说当前没对上，不能断言用户没说过。

重复判断基于已发送记录，不是检索次数。不给 `conversation_started_at` 时，使用当前完整 conversation scope 的已发送记录；提供该字段可以在复用 conversation ID 时划定本次聊天边界。用户再次主动询问同一往事可以覆盖重复抑制，但不会覆盖 `do_not_reference`。

## 未完成话题不是定时催问

`OpenLoop` 保存考试、面试、宠物复查、想以后分享的事或明确约定。它不是已经创建的提醒任务，也不证明应用具有日历或推送能力。

- `when_relevant`：只有话题相关时才考虑询问。
- `at_or_after_time`：到用户/宿主提供的时间后仍需话题相关；显式允许换话题时才可跨话题回访。
- `user_led`：用户重新开启这条事项才跟进。可传 `reopened_open_loop_id`；泛化的 `user_reopened_topic=true` 仍要求 topic 匹配，不能指向任意旧事。
- `never`：保存事项，不主动问。

状态为 `open / snoozed / waiting_for_reply / resolved / cancelled`。请求先看当前话语是否需要完整注意力；需要时返回 `hold`。没有“几天后情绪归零”“每隔若干轮必须问一次”的隐藏期限。

评估得到 `ask_now` 并不算问过。含该事项的回复拍收到发送回执后，才更新为 `waiting_for_reply`。重复回执不重复计数。更新可携带 `expected_revision`；旧计划中的事项版本发生变化时，不接受其过时回执。

这是数据库中的编排和回执约束，不是最终发送通道的强制锁。宿主仍必须在发送前重新检查事项状态，并协调消息 outbox，不能先把过时问题发出去再用回执错误补救。

## 一句自然纠错如何生效

`POST /api/v1/repairs` 接受：

| kind | 必要对象 | 结果 |
|---|---|---|
| `correct_memory` | `memory_id + replacement_content` | 沿用已有稳定身份，调用版本化更正 |
| `wrong_reference` | `memory_id` 或 `evidence_kind + evidence_id` | 当前 scope 内不再认作这次回忆的候选 |
| `stop_referencing` | 同上 | 不主动带出该证据；不等于删除原文 |
| `resolve_open_loop` | `open_loop_id` | 记录结果，停止追问 |
| `cancel_open_loop` | `open_loop_id` | 关闭事项，不再催问 |

`evidence_kind` 支持 `memory / event / turn`。旧的 `memory_id` 调用方式保留。反馈不会升级候选事实或改变用户关系状态。`welcome_reference` 可显式恢复当前 scope 中的引用资格。

已知证据血缘会参与抑制：原始回合被禁止引用，其派生记忆也不能绕路出现；记忆被否定，其已关联的原始回合也不会重新作为独立佐证。当前仅利用已有 `evidence_turn_ids` 和本次候选中可见的 `episode_id`，并非完整的跨摘要血缘图。

例如原始回合没有被抽取成 Memory，仍可提交：

```json
{
  "user_id": "alice",
  "scope": {
    "relationship_id": "relationship-a",
    "conversation_id": "conversation-a"
  },
  "kind": "wrong_reference",
  "evidence_kind": "turn",
  "evidence_id": "previously-referenced-turn-id"
}
```

这些 ID 由宿主从刚才的回复计划取得，不能交给用户填写。内核返回简短承认、继续聊天的表达指导，不生成审核表单。

## 语义分拍与打断

`ResponsePlan` 是供聊天端执行的计划，不直接生成回复文本，也不会真正发送消息。

每份计划保存生成时的 `config_fingerprint` 与 `policy_bundle` 身份，便于追溯为何选择某种表达规则。身份可追溯仍不代表该规则经过效果校准。

1. 第一拍根据当前话语回应；涉及回忆时不得提前声称已经想起。
   计划中的历史检索会排除本次 trigger，避免把用户刚提出的问题当作自身的证据。
2. 有必要时追加回忆、消歧或未完成事项的一拍。
3. 补充拍默认关闭。开启后需要宿主的 `host_release_signal`，不能自动计时释放。
4. 渠道不支持多拍时合为一个 `composed_response`，不会为每个内部步骤发送通知。
5. 新用户回合与旧计划取消在同一 SQLite 写事务内提交；延迟检索完成后，不能为已过时的 trigger 创建新计划。
6. `POST /response-plans/interrupt` 可在不保存用户正文时取消计划，例如当前输入未授权归档。

没有固定 `sleep`，也没有模拟呼吸或“假装思考”的延迟。已发送部分保留，取消只作用于后续待发送部分。重新规划会取消同一精确 scope 的旧 active 计划。

0.6 增加 staged 路径：`stage_response_plan()` 只保存当前话语首拍和待解析请求，立即返回；宿主可先生成并发送这一拍，再由自己的 worker 调用 resolve。resolve 才执行历史检索，并通过 plan revision 与幂等 resolution key 追加后续拍。已有完成结果的重复 key 直接返回既有计划；真正同时启动的重复 worker 可能重复计算，但只能提交一次。用户在此期间发来新消息、策略版本变化或计划被取消时，迟到结果不能写回。

`plan_response()` 仍保留完整同步规划，供单消息渠道和兼容调用使用。staged 路径只接受支持多拍的渠道，不能把原本的一条消息强拆成两条。内核没有线程池、任务队列或 transport；“异步”表示宿主可以在首拍后独立调度 resolve，而不是内核已经启动后台任务。

## 明确自然话语解释

`interpret_turn()` 只处理版本化配置中的明确表达，不推测用户真实情绪或反话：

- “先听我说 / 别给建议” → 当前表达优先，建议 `listen`；
- “你觉得怎么办 / 给我建议” → 建议 `problem_solve`；
- “你还记得 / 我以前说过” → 标记为明确回忆问题；
- “不是那个 / 你记错了” → 尝试纠正最近一次已发送证据；
- “以后别提 / 不要再提” → 尝试停止主动引用；
- “换个话题 / 先不说这个” → 取消旧待发送拍。
- “已经考完 / 已经通过 / 最后没去” → 当前话题唯一对应 OpenLoop 时记录结果。

倾听和建议同时命中时返回 `conflicting`，不替用户建立长期偏好。错配/停止引用只有在最近一次发送的合格证据目标唯一时才自动应用；零个或多个目标返回 `needs_target`，由聊天端问一个自然线索，不能展示内部 ID。

## 接口索引

以下路径均以 `/api/v1` 开头，沿用本地 API 认证：

| 方法与路径 | 用途 |
|---|---|
| `POST /open-loops` | 创建未完成事项 |
| `PATCH /open-loops/{id}` | 解决、取消、延后、重新开启或记录回访 |
| `POST /follow-ups/evaluate` | 判断现在是否适合问后续，不产生发送 |
| `POST /reference-feedback` | 记录错配、时机不当、太重复、不再引用或欢迎引用 |
| `POST /response-plans` | 生成并保存回复计划 |
| `POST /response-plans/staged` | 只生成当前话语首拍并保存待检索请求 |
| `POST /response-plans/interpreted-staged` | 解释自然控制语并生成首拍计划 |
| `POST /response-plans/{id}/resolve` | 幂等执行检索并追加后续拍 |
| `POST /turns/interpret` | 只解释一个已保存用户回合，可应用低风险动作 |
| `GET /response-plans/{id}` | 读取当前计划状态，需要 `user_id` |
| `POST /response-plans/interrupt` | 不保存正文的会话打断 |
| `POST /response-plans/{id}/beats/{beat_id}/sent` | 幂等记录实际发送及证据使用 |
| `DELETE /response-plans/{id}` | 取消尚未结束的计划 |
| `POST /repairs` | 一次自然纠错 |
| `GET /users/{id}/open-loops` | 查看未完成事项与历史状态 |
| `GET /users/{id}/reference-feedback` | 查看引用反馈 |
| `GET /users/{id}/response-plans` | 查看编排历史 |

CLI 对应 `create-open-loop`、`update-open-loop`、`evaluate-follow-up`、`interpret-turn`、`plan-response --staged`、`resolve-response-plan`、`mark-response-beat-sent`、`interrupt-response-plans`、`repair-conversation` 及列表命令。API/CLI 返回计划中的证据引用；生成端仍需按引用取回允许使用的内容并做最终预算编译。

## 小事召回与成本边界

`ConversationTurnInput` 新增 `retrieval_keys`、`embedding + embedding_space` 和 `episode_id`。keys 参与 FTS 与回合评分，不替代原文；仅由 key 命中的证据最多按 hedge 使用。同一 episode 的重复回合在事件回忆候选中只保留一项，原始记录不物理合并。“谁在什么时候说过”类查询仍保留不同原话，避免事件去重删除历史表达。

这还不是自动事件聚类。当前去重发生在有界候选池之后，重复 mention 仍可能挤占前置候选池；错误 episode_id 也尚无内核内的版本化拆分/合并协议。

未调用 LLM 或 embedding 服务的路径不会因体验规划新增模型调用，但本版没有成本和延迟实测。召回 `prompt_text` 的 token 预算不能当成整轮对话预算；回复计划、宿主系统提示、近期消息和输出仍需单独计算。原始向量检索仍是本地线性扫描，不是 100M token 能力证明。

## 验证状态

0.6 仅完成代码、文档和待运行场景用例。本轮没有执行测试、lint、类型检查、构建或上传。0.4 的既有通过报告不能用于为 0.5/0.6 放行。
