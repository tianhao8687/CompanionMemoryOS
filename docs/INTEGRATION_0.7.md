# 0.7 聊天宿主接入

目标是少写胶水代码，不引入模型厂商、任务队列或其他数据库。安装、`init`、`serve` 沿用原流程。应用版本 `0.7.4`，数据库版本 `8`；启动会兼容升级旧数据库。升级前请保留自己的备份。

## 安装验证范围

本地源码包和 wheel 已分别在独立 Python 3.12 环境中安装验证，包含安装后的 `init` 和实际 `serve` HTTP 检查。本轮没有发布到 PyPI 或上传 GitHub；下载 wheel 后可在自己的环境中运行：

```bash
python -m pip install ./companion_memoryos-0.7.4-py3-none-any.whl
companion-memoryos init
companion-memoryos serve
```

wheel 不包含 Python、第三方依赖或分词器编码缓存。安装依赖及分词器首次获取编码资源可能需要网络；完全离线分发需要另外准备这些资源。本轮没有验证 Windows/macOS。

## 最短接入路径

1. 宿主取得采集授权，把普通消息提交到 `POST /api/v1/turns`，取得 `turn.id`。
2. 宿主调用自己的模型，按 `TurnInterpretation`（回合解释）的 JSON schema（结构约束）生成候选。结构约束可由 `TurnInterpretation.model_json_schema()` 取得，也在接口文档中可见。
3. 宿主把输出提交到 `POST /api/v1/turns/{turn_id}/interpretation`。原始聊天已经保存，模型失败不影响它。
4. 调用已有的 `/api/v1/response-plans/interpreted-staged` 创建分阶段回复计划，取得首拍；宿主完成真实生成和发送后提交发送回执。后续仍使用原来的 `resolve`（解析完成）协议。

接口沿用现有 Bearer（持有者令牌）授权。身份、作用域、授权和模型指纹由宿主提供，不属于模型输出。一个回合接受一次不可变解释；相同完整请求重试返回原回执，不重复创建记忆或事项。相同回合提交不同解释会返回冲突，需使用现有纠正接口或新的原始回合。

示例请求，其中主体 `wang` 由模型识别，用户身份与关系范围由宿主绑定：

```json
{
  "user_id": "user-a",
  "scope": {
    "companion_id": "companion-a",
    "relationship_id": "relationship-a",
    "conversation_id": "chat-a"
  },
  "model_fingerprint": "your-model-and-prompt-revision",
  "idempotency_key": "turn-123:interpretation-v1",
  "model_output": {
    "topics": ["咖啡"],
    "state_claims": [{
      "title": "小王的咖啡偏好",
      "content": "小王喜欢加燕麦奶的咖啡",
      "predicate": "coffee_preference",
      "subject_actor_id": "wang",
      "epistemic_kind": "observation"
    }]
  }
}
```

也可把整个请求保存为 JSON 后执行：

```bash
companion-memoryos apply-interpretation TURN_ID interpretation.json
```

### 候选不是自动确认

`speech_spans`（说话片段）、`topics`（话题）、`state_claims`（状态主张）、`memory_candidates`（记忆候选）、`open_loop_candidates`（未完成事项候选）均可省略。状态主张必须给出主体，不能靠“外层消息来自用户”把小王的喜好变成用户自述。

模型产生的记忆沿用 `remember()` 的候选生命周期，来源标为 `machine`（机器观察）。它不能确认授权、直接晋升用户自述、覆盖当前状态或修改 `PolicyConstraint`（行为约束）。观察类候选可由宿主使用现有复核/纠正流程处理；不要求在每轮聊天弹出用户确认框。未晋升的细节仍能通过原始回合召回。

未完成事项只以 `user_led`（由用户重启话题）模式创建，不自动承诺提醒或主动回访。说话片段保存在解释记录里，原始 `ConversationTurn`（对话回合）的正文、原始片段和摄入哈希不变。话题只作为额外检索键，不作为独立事实。

本地明确话语规则先执行。只有本地未识别时，模型的 `discourse_signals`（话语意图）才补位，例如把“你怎么又把他们两个搞混了”映射为 `wrong_reference`（引用错配）。模型不能用“建议模式”覆盖已经命中的“先听我说”。

## 主体和当地日期

现有状态接口增加可选 `subject_actor_id`（状态主体）。省略时查询当前 `user_id`；查询 AI 自身时填 `companion_id`，第三人使用稳定人物标识。显式相同状态键的覆盖也按主体、谓词、现实层隔离。

`RecallRequest`（召回请求）新增 `state_subject_actor_id` 和 `calendar_timezone`（自然日期时区）。后者默认为 `UTC`（协调世界时）；只影响“今天/昨天/上周”等日期解释，不改变数据库存储时区。分阶段快捷接入也接受该字段。

```json
{
  "user_id": "user-a",
  "query": "今天聊过什么？",
  "calendar_timezone": "Asia/Singapore",
  "as_of": "2026-09-01T17:00:00Z",
  "scope": {
    "companion_id": "companion-a",
    "relationship_id": "relationship-a",
    "conversation_id": "chat-a"
  }
}
```

该查询的本地日期是 9 月 2 日，数据库查询窗口为 `09-01 16:00Z` 至 `09-02 16:00Z`，右端不包含。夏令时按真实日历边界换算，不能固定减去 24 小时。

## 跨轮事件

模型可附带 `episode_hint`（事件归属建议）：

```json
{"action": "new", "title": "第一次面试", "participant_actor_ids": ["company-a"]}
```

后续提交：

```json
{
  "action": "attach",
  "episode_id": "已有事件标识",
  "continuity_turn_id": "该事件中较早的原始回合标识",
  "participant_actor_ids": ["company-a"]
}
```

自动归属检查同用户、同关系授权域、现实层、源回合可用、时间顺序、话题交集，以及已有参与人时的参与人交集。`confidence`（模型置信分数）只被保存，不作为事实或归属阈值。默认没有“超过几天就一定不是同一件事”的隐藏数字；宿主若需要限定相邻事件间隔，在解释请求中传 `episode_max_gap_seconds`（允许的最长间隔秒数），该限制进入请求哈希。它是宿主产品策略，不是情绪有效期。

| 接口 | 用途 |
| --- | --- |
| `POST /api/v1/episodes` | 显式创建事件 |
| `GET /api/v1/episodes` | 按用户和作用域列出事件 |
| `GET /api/v1/episodes/{id}/turns` | 获取授权范围内的原始回合，按发生时间排序 |
| `POST /api/v1/episodes/{id}/attach` | 归入事件；重新归属须提交旧 `expected_episode_id` |
| `POST /api/v1/episodes/{id}/merge` | 把 `source_episode_id` 合入目标，保留原事件的合并指向 |
| `POST /api/v1/episodes/{id}/split` | 把指定 `turn_ids` 拆为新事件 |

修改可携带 `expected_revision`（预期版本），版本不一致则拒绝。修改归属会使已有摘要失效，不改原文；合并不是永久压平证据。查询事件原文时必须明确授权范围；普通召回仍遵守原有精确会话隔离，不因有了关系级事件而自动扩大检索范围。旧宿主自带的 `episode_id` 仍兼容，不会被启动迁移擅自重写。

## 真实使用记录

原有使用记录增加 `use_type`（使用类型）：`explicit_reference`（明确引用）、`soft_reference`（轻引用）、`silent_influence`（仅影响回答）、`clarification`（用于澄清）。旧请求根据 `use_mode`（表达确定性）推导，旧数据库迁移保留原记录。

回复计划只代表可能使用。实际发送回执可携带 `silently_used_memory_ids`，限定为该已解析计划中确实参与回答的静默记忆。系统记录记忆标识、回复组、类型、时间，不保存静默影响的输出正文或正文哈希。重投不会重复计数。静默使用不计入现有“已向用户提过”的重复抑制，也不启用新的自动降权。

## 可替换的两个轻量接口

```python
from companion_memoryos.service import CompanionMemoryService


class MyTokenCounter:
    def count(self, text: str) -> int:
        return my_model_tokenizer_count(text)  # 宿主提供自己的计数函数


service = CompanionMemoryService(store, config, token_counter=MyTokenCounter())
```

只要求 `count(text)`；默认仍为 `TiktokenTokenCounter`。召回结果记录实际计数器标识，不再把自定义计数器冒充默认编码。

`SemanticIndex`（语义索引）仅有 `upsert/delete/search`（写入、删除、查询）；可通过 `MemoryStore(database, semantic_index=...)` 注入。默认 `SQLiteSemanticIndex` 直接使用原有向量表，无数据迁移。默认实现先按授权、有效期、模型命名空间和向量维度过滤，再逐条计算相似度，只在内存保留有界候选堆。

这仍是精确扫描，不是大规模近邻索引。替代实现必须在打分前按请求授权范围过滤，并根据主库处理生命周期与有效时间；主库还会再次验证返回标识。外部索引事务、全量重建和迁移协议不在 0.7 中提供，不能把注入接口本身当作已支持任意外部向量库。
