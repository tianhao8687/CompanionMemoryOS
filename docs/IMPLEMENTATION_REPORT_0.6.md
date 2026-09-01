# 0.6 聊天运行时桥接实现报告

日期：2026-09-01。状态：实现完成；2026-09-02 集中工程验证通过，仍为 alpha。

本轮继续解决“用户实际聊起来是什么感受”，重点补上 0.5 的两个明确缺口：宿主需要手工识别常见控制语，以及回复计划必须等待完整检索后才能返回。

## 本轮结果

| 用户场景 | 0.6 行为 |
|---|---|
| “先听我说，别给建议” | 识别为明确倾听，当前话语优先，旧事项本轮 hold |
| “你觉得怎么办” | 建议 problem-solve，不把一次请求写成永久偏好 |
| “你还记得上次那个吗” | 首拍只能接住问题；检索完成前不说“记得”或“你没讲过” |
| “不是那个，你记错了” | 最近一次已发送证据唯一时自动记录错配；不唯一时返回 needs-target |
| “以后别再提这件事” | 唯一目标时停止主动引用，不冒充删除 |
| “算了，换个话题” | 取消旧计划尚未发送的拍，迟到检索不能写回 |
| “考试已经考完了” | 仅在当前话题唯一对应一条 OpenLoop 时关闭；否则 needs-target |
| 长尾检索较慢 | 当前话语首拍先持久化并可发送，历史拍由宿主异步 resolve |
| resolve 重试或并发 | resolution key 幂等；revision、policy version 与新回合共同阻止陈旧结果 |
| 单消息渠道 | 继续同步合并为一条，不为追求“像人”强行拆气泡 |

## 一、明确话语解释器

新增 `discourse.py` 和 `[discourse]` 配置。当前实现是可解释、无模型调用的中文明确短语匹配，不输出虚构概率。支持七类信号：

- `listen_only`
- `advice_requested`
- `memory_question`
- `wrong_reference`
- `stop_referencing`
- `topic_switch`
- `outcome_reported`

倾听与建议同时出现时返回 `conflicting`，不自动选择，也不改变长期 SupportStrategy。若回合带 SpeechSpan，只读取 `quote_depth=0 + real_world + 当前 actor` 的直接区间，转发原话或角色台词不能操作用户运行时。解释结果可直接形成 ResponsePlan 的 goal、`user_asked_memory_question` 与 `current_turn_requires_full_attention`。

低风险动作包括：取消旧待发送计划；对最近一次实际发送的唯一证据记录错配/停止引用；以及在当前 topic keys 唯一对应一条 OpenLoop 时记录明确事项结果。目标为零或多个时返回 `needs_target`；系统不能猜一个，也不能让用户填写内部 ID。

自动入口默认允许 recall，但明确要求“先听我说/别分析”时不为个性化额外启动历史检索，除非同一句又明确提出回忆问题。这样当下优先不仅改变表达，也直接减少无意义 token 与延迟。

新增入口：

- `POST /api/v1/turns/interpret`
- `POST /api/v1/response-plans/interpreted-staged`
- CLI `interpret-turn`

## 二、分阶段 ResponsePlan

数据库 schema v7 为 ResponsePlan 增加：

- `revision`
- `resolution_status`
- 持久化 `resolution_request_json`
- `resolution_key`
- `resolved_at`

stage 只做本地读取与写入，生成一个 `CURRENT_TURN` 首拍。它不执行 recall，所以首拍 guidance 不可能提前引用历史。宿主发送首拍后，计划仍保持 `active + pending`，不会因为当前暂时没有其他 beat 就误判完成。待解析请求只在 pending 期间保存，resolve 或取消后清空，减少重复保留查询正文。

resolve 从数据库读取原请求，执行 recall、引用反馈、会话内重复检查、Memory Use、OpenLoop 与后续 beat 编译。写回时再次检查：

1. 计划仍 active；
2. expected revision 未变化；
3. 当前 policy version 等于计划版本；
4. trigger 后没有新的 user turn；
5. resolution key 没有与另一请求冲突。

同一 key 在已有完成结果后重放，会在发起 recall 前直接返回已保存计划，避免普通网络重试重复消耗检索。两个真正同时开始的 worker 仍可能各自完成一次读取计算，但只有一个结果能提交；要完全消除这类并发计算还需要可恢复的任务租约。若用户先发了新消息，Conversation Ledger 会原子取消旧计划；已经运行的检索最多浪费本次计算，不能把结果插回聊天。

新增入口：

- `POST /api/v1/response-plans/staged`
- `POST /api/v1/response-plans/{id}/resolve`
- CLI `plan-response --staged`
- CLI `resolve-response-plan`

兼容的 `POST /response-plans` 与 `plan_response()` 仍同步生成完整计划，单消息渠道继续使用这一路径。

## 三、魔法数字处理

本轮没有加入固定等待秒数、短语置信阈值、自动目标候选上限或“几轮后恢复”规则。话语短语族位于 `defaults.toml`，参与配置指纹；冲突与唯一目标使用协议状态，不使用相似度阈值。`discourse.py` 已加入魔法数字 AST 用例清单。

配置化只代表可见和可版本化，不代表短语覆盖已经校准。当前中文表达集是原型规则，真实上线前仍要评测漏识别、误识别、方言、否定作用域和句内改口。

## 四、已通过的集中场景

- 明确倾听语言直接形成 pending 首拍；
- 首拍已发送时计划仍 active；
- resolve 后后续拍变为 ready；
- 同一 resolution key 重放幂等；
- 新 user turn 使 pending retrieval 失效；
- 最近一次唯一已发送证据接受“不是那个”自动修复；
- 引用 SpeechSpan 中的控制语不能操作用户运行时；
- 明确结果只关闭唯一 topic-matched OpenLoop；
- HTTP interpreted-stage → 首拍回执 → resolve 闭环；
- v6 数据库补齐 v7 staged resolution 列；
- discourse 文件纳入无魔法数字扫描。

## 五、没有完成或不能宣称的部分

1. **没有聊天模型。** guidance 不是最终回复，系统不生成用户看到的中文文案。
2. **没有后台 worker。** staged API 使宿主可以异步调度，但内核不会自己启动任务。
3. **没有 outbox 或 transport。** 发送、重试、网络失败与最终 transport gate 仍由宿主负责。
4. **不是完整 NLU。** 当前只识别明确短语；反话、长距离否定、句中多次改口与方言不能声称可靠。
5. **自动修复只看最近一次实际发送证据。** 它不是任意历史实体解析器；目标不唯一时必须自然澄清。
6. **OpenLoop 自动解决有严格前提。** 只处理明确结果短语 + 宿主当前 topic keys + 唯一未完成事项；没有可靠 topic extraction 时仍需宿主或用户定位。
7. **没有真实延迟或 token 数据。** staged 架构减少首拍对 recall 的依赖，但尚未测量 P50/P95、队列成本或用户中断率。
8. **100M、静态加密和彻底删除阻断不变。** 本轮不改变此前 Go/No-Go 结论。

## 六、验证状态

2026-09-02（Asia/Singapore）完成集中验证：151 tests、84% overall coverage、Ruff lint/format、strict mypy（20 个源码文件）、依赖一致性、sdist/wheel 构建、CLI 全新目录初始化、SQLite 完整性与 schema v7 均通过。

集中验证发现并修复了原始回合 embedding 表白名单遗漏，以及三类局部变量类型复用问题。详细命令结果、用户体验对抗结论和仍然有效的生产阻断见 [0.6 集中验证报告](VALIDATION_REPORT_0.6.md)。本轮没有进行 100M 压测、真实用户研究、法证删除或性能测试，因此只能称“工程门禁通过的 0.6 alpha 原型”。
