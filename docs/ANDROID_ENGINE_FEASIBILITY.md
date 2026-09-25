# 独立手机版路线验证

日期：2026-09-25。基线提交：`4a6b59b`。

## 结论

继续使用 Flutter 玻璃界面。Android 优先验证 **Flutter + Chaquopy 内嵌 Python +
应用私有目录中的 SQLite**，复用现有聊天和记忆代码；电脑与手机各自保存数据，
不连接电脑、不做双端同步。以后上云时通过另外的数据接入实现访问服务端引擎。

这是有条件的技术候选，**尚未验证为可交付的独立手机版**。本轮实际执行了 Android
目标依赖下载，Python 3.12 与 3.13 均缺少三个关键原生包的现成二进制文件。
因此“给现有 Flutter 工程加插件即可打包全部 Python 代码”的路线目前未通过依赖关卡。
下一项最小验证是交叉编译这些依赖并在 Android 上加载，再决定是否扩大客户端开发。

本次新增可复跑的依赖探针与本报告；没有修改业务引擎、Flutter 页面和正式构建配置。

## 本轮实际做了什么

探针：[probe_android_engine.py](../clients/xinyu_flutter/tool/probe_android_engine.py)。

- 面向 ARM64、最低 Android API 24，分别检查 CPython 3.12 / 3.13。
- 同时查询 PyPI 与 Chaquopy 官方包源；限定 Android / 通用 wheel，不接受 Windows、
  manylinux 二进制包，不在本机虚拟环境安装目标包。
- 8 个包 × 2 个 Python 版本，共 16 次实际解析和下载。
- 成功下载的 wheel 只表示单包候选可用，使用 `--no-deps`；没有把它等同于完整依赖解析。
- 保存成功与失败日志，并区分网络错误、解析失败和无兼容二进制，避免网络故障被判成包不存在。
- 读取下载包中的 ELF 头，检查 ARM64 类型与 LOAD 段对齐，不执行其中的代码。

| 包 | Python 3.12 | Python 3.13 | 对项目的意义 |
|---|---|---|---|
| `tiktoken >=0.9,<1` | 无兼容二进制 | 无兼容二进制 | 实际 token 预算需要它 |
| `pydantic-core >=2.27,<3` | 无兼容二进制 | 无兼容二进制 | Pydantic 2 模型的核心依赖 |
| `rpds-py >=0.7` | 无兼容二进制 | 无兼容二进制 | JSON Schema / referencing 依赖链 |
| `pydantic >=2.10,<3` | 通用 wheel | 通用 wheel | 外层包可用，核心缺失仍阻塞运行 |
| `regex >=2022.1.18` | Android wheel | Android wheel | 两个候选的对齐不同，见下文 |
| `PyYAML >=6,<7` | Android wheel | Android wheel | 两个候选的 LOAD 对齐均为 16 KB |
| `mcp >=1.30,<2` | 通用 wheel | 通用 wheel | 不代表其所有传递依赖可用，也不授权启用工具 |
| `tzdata >=2025.1` | 通用 wheel | 通用 wheel | 移动端应显式提供时区数据 |

“无兼容二进制”仅针对本次包源、版本范围、Python 版本、ARM64 和最低 API 24 的组合；
不表示包无法从源码交叉编译，也不表示所有 Android 版本都不存在其他组合。

## 为什么优先尝试 Python 3.13

实际下载的 `regex-2023.10.3`（CPython 3.12 / ARM64）LOAD 段对齐为 4096 字节；
`regex-2024.9.11`（CPython 3.13 / ARM64）为 16384 字节。两种 Python 对应的
`PyYAML-6.0.3` 都是 16384 字节。检查结果保存在本轮目录的 `elf-inspection.json`。

这为选择 3.13 提供了一项具体依据，但 LOAD 对齐检查不等于完成 16 KB 设备兼容验收。
后续还需检查 RELRO、APK ZIP 对齐和真实加载行为。Android 官方提供了这些分别独立的
[检查方法](https://developer.android.com/guide/practices/page-sizes)。

Chaquopy 17 支持 Python 3.13 和当前工程使用的 AGP 9.1，最低 API 为 24；
其发布说明也建议为 16 KB 设备优先考虑 Python 3.13 及以后版本。
见[版本矩阵](https://chaquo.com/chaquopy/doc/current/versions.html)和
[发布说明](https://chaquo.com/chaquopy/doc/current/changelog.html)。

## 建议落地结构

```text
Flutter 玻璃界面
    ↓ CompanionRepository 接口
AndroidEmbeddedRepository（待实现）
    ↓ Android 原生桥；工作线程执行，流式事件回传
Chaquopy / Python 3.13
    ↓ 复用现有聊天、人格、记忆引擎
应用私有目录 SQLite（唯一记忆事实源）
```

现有 `LocalRepository` 是访问电脑回环 HTTP 服务的适配器，不是手机内置引擎。
新增 Android 实现后，客户端与现有桌面实现共用接口；以后增加云端实现时继续复用页面。
云端接入需要独立认证和作用域隔离，不自动合并电脑与手机的数据。

这条结构尚未接入代码，以下项目属于后续验证范围：

1. **原生依赖关卡**：固定兼容版本，交叉编译 `tiktoken`、`pydantic-core`、`rpds-py`，
   包括它们所需的完整传递依赖。先覆盖 ARM64，再补模拟器架构；校验产物哈希和 16 KB 对齐。
2. **最小设备关卡**：在新建的合成数据目录导入所有依赖，启动原记忆引擎，确认 SQLite
   FTS5 / WAL、中文检索、准确 token 计数和时区可用。随包提供所需 tokenizer 数据文件。
3. **业务关卡**：验证聊天保存、同一请求重试幂等、进程重建、记忆更正与遗忘及来源清理。
   继续用同一套记忆记录和证据/版本链，不创建独立偏好库或精简版记忆实现。
4. **客户端关卡**：接入 Flutter，验证流式取消、输入法、页面恢复、长聊天滚动和玻璃性能。
   Python 与数据库操作离开 UI 线程，串行管理引擎访问及生命周期。
5. **移动能力边界**：先拆开核心聊天与桌面 MCP、ADB、微信渠道、后台调度的依赖。
   测试中保持这些外部能力关闭；手机后台提醒需要平台适配，不能沿用桌面常驻进程假设。

这次没有使用降级到 Pydantic 1、近似字符计数、空实现或删除记忆约束来绕过依赖。
完全重写为 Dart 会引入另一套复杂的业务行为；当前优先验证复用 Python 的成本。

## 环境和验证状态

本次环境的 PATH 未发现 Flutter、Java、ADB，检查的常用 SDK 目录也未发现先前文档所列
工具链。WSL 命令报告尚未安装发行环境。因此本轮没有运行 Gradle、交叉编译、APK 安装、
模拟器或手机测试；此前原型的 Windows / Android 构建记录不能替代本次独立引擎验证。

iOS 不使用 Chaquopy。后续需要独立的 CPython 嵌入、依赖构建、Xcode 签名和真机验收；
本轮没有验证 iOS。参见 [Python iOS 嵌入说明](https://docs.python.org/3/using/ios.html)。

| 检查 | 结果 |
|---|---|
| Android 单包依赖探测 | 阻塞：两组 Python 都缺 3 个关键原生二进制 |
| ELF 头检查 | 已执行；仅验证文件头中的 LOAD 对齐 |
| 探针分类检查 | 6 项通过，包含网络失败和非 Android wheel 拒绝 |
| Ruff | 通过 |
| mypy | 107 个源文件通过 |
| pytest | 876 通过、1 失败、2 跳过 |
| 实际应用 `lifecycle` | 离线后端通过 |
| 实际应用 `chat_quality` | 离线后端通过；语言质量仍阻塞 |
| Android 构建/运行、iOS | 未执行 |

pytest 失败项为
`tests/test_blended_memory_repairs.py::test_natural_location_forgetting_deletes_raw_sources_even_without_memory_card`。
单独复跑仍失败：来源正文已被脱敏，但 `deletion_state` 为 `active`，断言要求 `forgotten`。
本轮未修改 `companion_agent`、`companion_memoryos` 或 `tests`，因此将它记录为当前基线问题，
没有为通过手机评估而改写既有断言。发布前应另行修复并验证其遗忘语义。

没有访问日常数据库，没有调用真实模型，没有启用真实渠道、设备、MCP 或外部动作。
离线应用进程测试是 Windows 上的后端证据，不是 Android 运行证明，也不评价语言质量。

## 运行编号与复现

运行编号：

- Android 依赖探针：`android-engine-20260925T084032Z-2f6ded1d`
- 离线 `lifecycle`：`4ac12389-4ba9-4870-b06f-a38aa3ea06b5`
- 离线 `chat_quality`：`3bae5955-abf4-4f58-9568-0aa526b68827`

报告、下载包、失败日志和基线单测复查日志保存在上述 `.agent-tests` 目录中，未加入源码。
探针数据是技术检查证据，不是指令或授权来源。

```powershell
.\.venv\Scripts\python.exe clients/xinyu_flutter/tool/probe_android_engine.py
.\.venv\Scripts\python.exe clients/xinyu_flutter/tool/probe_android_engine.py `
  --inspect-wheels-in .agent-tests/android-engine-20260925T084032Z-2f6ded1d
```

默认探针每个包最多等待 90 秒，关闭网络自动重试，以四个并发下载任务检查两个 Python
版本。只有全部单包存在候选时返回 0；缺包或结果无法确认时返回 2。成功退出仍然仅代表
候选文件齐备，需要另外进行完整 Android 依赖解析、构建和运行验收。
