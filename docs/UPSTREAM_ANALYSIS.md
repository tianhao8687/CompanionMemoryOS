# Upstream analysis

源项目：`tianhao8687/MemoryOS`
审计基线：`c0f0547`（`Sync natural-language MemoryOS control (#15)`）

本项目是在代码级审计后独立实现的，不是依据 README 改名，也没有修改源仓库。

## 保留的机制

- SQLite WAL + FTS5 作为唯一事实源；
- 候选优先、显式确认/拒绝；
- 证据来源、内容哈希与审计事件；
- `supersedes_id`、有效时间和过期时间；
- 逻辑遗忘与物理清除；
- 强用户作用域隔离；
- 固定约束和可复现配置指纹。

## 替换的领域概念

| MemoryOS 编程场景 | CompanionMemoryOS 陪伴场景 |
|---|---|
| repo / branch / task 作用域 | user 作用域 |
| coding claims / constraints | 身份、偏好、边界、支持策略 |
| 文件与源码证据 | 对话来源与最小摘录 |
| 代码新鲜度与源码锚点 | 事件时间、保留期限与当前表达优先 |
| 工程上下文编译 | 分区 CompanionContext |
| SWE/DSH 评测 | 边界、误归因、隐私与操纵风险评测 |

## 明确未移植

- 仓库、分支、任务和代码实体模型；
- tree-sitter、Git 新鲜度和源码行锚点；
- 编程声明、代码 RRF/ANN 实验与工程基准；
- 任何会鼓励情感依赖、排他或参与度操纵的机制。
