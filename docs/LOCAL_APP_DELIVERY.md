# Windows / Android 本地版交付记录

日期：2026-09-25。当前为**实现与验证中，尚未交付完整的两端安装包**。
两端数据独立；不引入账户同步，也不部署服务器。

## 本次实现

- 复用同一个 Python 记忆引擎、SQLite 数据和证据/版本链。
- Flutter 正常入口自动接入本机引擎，保留玻璃界面、桌面/窄屏布局。
- Windows 使用随包附带的独立引擎进程；Android 接入 Chaquopy 嵌入式运行时。
- 随机回环端口、启动凭证、单数据目录进程锁、拥有者退出时停止引擎。
- 流式聊天、停止回复、保留请求 ID 的重试、历史分页、自定义风格、记忆更正/遗忘。
- 系统安全 Key 存储接入、完整 SQLite 备份与恢复、恢复前副本和损坏设置拒绝。
- 默认回复仍是离线规则演示；真实模型需用户配置 API 并授权，不是离线大模型。
- 本地应用不启动外部渠道和后台定时服务。Android 禁用系统云备份与自动设备迁移。

构建和使用方法见 [客户端说明](../clients/xinyu_flutter/README.md)。

## 实际产物与环境边界

| 层级 | 当前状态 |
|---|---|
| Windows 独立 Python 引擎 | 已打包并运行验收，用户无需安装 Python |
| Flutter 共享界面 | 静态分析通过，13 项测试通过 |
| Windows 完整图形程序 | 未构建；当前机器没有 Visual Studio C++ 桌面工作负载 |
| Android 独立 APK | 未生成；原生依赖尚未完成交叉编译，SDK 平台组件也未完成配置 |
| Android Keystore、FTS5、16 KB、安装/启动/恢复 | 未在 Android 环境验证 |
| 真实模型聊天质量 | 未调用模型，不做通过判断 |

独立引擎目录：
`dist/xinyu-local/engine-final/xinyu-engine/`，其中 exe 与 `_internal` 必须保持在一起。
这是供桌面客户端启动的组件，**不是已经可双击使用的聊天软件**。
exe SHA-256：`a0106a0581215f371eb15288bf97852944e80a331c3aae693a214058439f63b8`。

Flutter 3.47.5 / Dart 3.13.4 已安装并用于分析和测试。Windows 构建工具的微软安装器
签名验证为有效，但本会话没有管理员权限，安装退出码为 1602；后续 Flutter doctor
也确认 Visual Studio 未安装。Android 缺少 `pydantic-core`、`rpds-py`、`tiktoken`
的目标 wheel；本次已经提供构建脚本，但没有把 Windows/Linux wheel 冒充 Android wheel。
官方 [cibuildwheel Android 构建要求](https://cibuildwheel.pypa.io/en/stable/platforms/#android)
需要受支持的 Linux/macOS 构建主机。当前机器没有可用的 WSL 或 Docker 环境。

## 本轮验证

- `ruff check .`、`ruff format --check .`、`mypy companion_agent companion_memoryos` 通过。
- Python 全量回归：**878 通过、1 失败、2 跳过**。
  失败为前序已经记录的
  `test_natural_location_forgetting_deletes_raw_sources_even_without_memory_card`：
  测试要求来源轮次为 `forgotten`，当前实际仍是 `active`。本轮未修改这项删除语义，
  也没有跳过或改写断言来使其变绿。完整结果保留在
  `.agent-tests/tooling/local-app-regression.xml` 与同名 `.log`。
- 原生引擎新增进程测试通过：凭证保护、相同请求不重复入库、聊天重启持久化、
  备份恢复、恢复前副本、无效文件/设置拒绝、EOF 停止和重复实例互斥。
- Flutter 静态分析通过。13 项测试覆盖 320/390/1920 宽度、自定义风格、Key 设置、
  备份控件、失败重试、UTF-8 流、凭证更新、原始二进制备份传输和启动失败呈现。
  新增窄屏测试发现并修复回复方式下拉框溢出；失败日志和修复后的日志分别保留在
  `.agent-tests/tooling/flutter-local-test.log` 与 `flutter-local-test-2.log`。
- 所有测试使用合成数据。未访问日常聊天库；没有真实模型调用。

实际进程运行 ID：

| 运行 ID | 结果与覆盖 |
|---|---|
| `native-bundle-9afb871faf4d4e6a9f16dcb88f5ce487` | 第一轮 Windows 冻结引擎通过，界面未验收 |
| `native-bundle-10c893a507f940298d16ca396767ec9a` | 加入损坏设置拒绝后的冻结引擎通过，界面未验收 |
| `2e47a578-2565-4df0-bc24-a39a58dfdfcb` | 原应用生命周期场景通过 |
| `d843d5b1-0fa0-4798-89a6-98105df77e28` | 聊天流程通过；语言质量因未授权真实模型而 blocked |

运行数据和原始报告位于各自 `.agent-tests/<运行ID>`，不提交到仓库。

## 后续构建入口

本地脚本为 `clients/xinyu_flutter/tool/build_local.ps1`，Android 原生依赖脚本为
`clients/xinyu_flutter/tool/build_android_wheels.py`。

另外已准备 [GitHub Actions 构建流程](../.github/workflows/local-apps.yml)：
Linux 生成 Android 原生 wheel，Windows runner 分别打包桌面和手机程序；
只生成可下载的构建产物，不发布 Release、不部署服务、不连接真实模型。
流程尚未上传或执行，YAML 结构已在本地解析检查，不能据此宣称远程构建成功。
使用它需要将本次改动提交到项目仓库并使用 Actions 额度。Android 产物采用开发签名，
仍需后续正式签名与手机验收；构建通过不能替代实际设备验证。
只有手动运行或向 `codex/local-apps-*` 专用分支推送才触发，不在普通分支推送时打包。
