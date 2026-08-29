# Architecture

## 数据流

```mermaid
flowchart TD
    A["结构化 MemoryInput"] --> B["同意与敏感度策略"]
    B -->|丢弃| C["不落盘"]
    B -->|候选| D["候选审核"]
    B -->|生效| E["SQLite 事实源"]
    D -->|确认| E
    D -->|拒绝| F["审计状态"]
    E --> G["FTS 候选集"]
    G --> H["六维评分 + 边界置顶"]
    H --> I["CompanionContext"]
```

## 模块职责

| 模块 | 职责 |
|---|---|
| `schemas.py` | 领域枚举、严格输入输出模型 |
| `config.py` | TOML 合并、约束验证、配置指纹 |
| `policy.py` | 同意、敏感度、审核和保留期限决策 |
| `database.py` | SQLite schema、WAL、FTS5 和完整性检查 |
| `store.py` | 事务、证据、审计、生命周期和用户作用域 |
| `scoring.py` | 中英文 token、FTS 查询和可解释评分 |
| `service.py` | 记忆用例、边界固定召回和上下文编排 |
| `api.py` / `cli.py` | 本地 HTTP 与命令行接口 |

## 真相与生命周期

状态转换为：

```mermaid
stateDiagram-v2
    [*] --> candidate: 推断或需复核
    [*] --> active: 明确授权
    candidate --> active: confirm
    candidate --> rejected: reject
    candidate --> expired: 到期
    active --> superseded: 同 stable_key 更新
    active --> forgotten: forget
    active --> expired: 到期
    forgotten --> [*]: purge
    superseded --> [*]: purge
```

`purge` 可以从任意已存在状态执行。删除后不保留正文，只保留最小审计元数据。

## 召回

1. 过期状态结算。
2. FTS 命中、全部有效边界和近期记忆组成候选池。
3. 按词面、显著性、时效、情绪、需要、意图连续性评分。
4. 边界固定在最前；普通记忆受条数和字符预算约束。
5. 输出分区上下文、评分原因、待审核数和配置指纹。

召回不会读取 `candidate`、`rejected`、`forgotten`、`expired` 或 `superseded` 记忆。
