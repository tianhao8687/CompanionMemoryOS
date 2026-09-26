# Windows / Android 本地版交付记录

2026-09-26 最新本地 Android 测试包为 **0.2.8（0.2.8+11）**，将“回到底部”按钮固定在
输入框上方右侧，空白会话也显示入口，并修正轻微上翻被当作已经到底的问题。
见 [0.2.8 安装包与检查记录](ANDROID_028_DELIVERY.md)。
它保留 [0.2.7](ANDROID_027_DELIVERY.md) 的缺 Key、聊天授权及操作失败原因弹窗，
保留输入，由用户选择是否前往设置。
它保留 [0.2.6](ANDROID_026_DELIVERY.md) 的设置、下拉选中项、角色主页、消息菜单及
日期时间弹窗的大圆角与胶囊形，以及玻璃质感。
它包含 [0.2.5](ANDROID_025_DELIVERY.md) 的收藏、多选复制/收藏、自然聊天节奏、
草稿与阅读位置恢复、回到底部按钮及独立角色主页；没有新增重发/重新生成。
它也包含此前手账、纪念日约定、共同回忆、
引用、角色图片、自动滚动、完整遗忘、搜索、表情包与主动通知；
[0.2.4 r2 自行测试记录](ANDROID_024_SELFTEST.md)及更早版本保留。
2026-09-26 用户已明确同意上传源码和这个已测试的 APK，
发布入口为 [心隅 0.2.8 Android 测试版](https://github.com/tianhao8687/CompanionMemoryOS/releases/tag/xinyu-v0.2.8)。
本次不重新运行 GitHub Actions 打包。尚未完成 Android 真机验收。
Windows 本轮未重新打包；下列旧安装包不含这些功能。

日期：2026-09-25。**Windows 安装程序、免安装包和 Android APK 已构建并下载，包含水润界面与字号更新。**
两端数据独立；不引入账户同步，也不部署服务器。

**Android 0.2.0 启动缺陷更新：** 用户在红米 K50 实测发现“本机引擎未连接”。
下文 0.2.0 APK 的构建和静态检查记录保留作历史证据，不再作为可用手机版推荐。
修正包和独立 Android 运行结果见 [Android 启动修复记录](ANDROID_STARTUP_REPAIR.md)。

**当前交付约束：** 先本地修改、检查和测试，展示结果，用户明确同意后再上传 GitHub
或手动启动打包。本分支安装包流程仅保留 `workflow_dispatch` 手动入口，
代码推送不自动打包；常规源码 CI 与安装包构建分开。

## 本次实现

- 复用同一个 Python 记忆引擎、SQLite 数据和证据/版本链。
- Flutter 正常入口自动接入本机引擎，保留玻璃界面、桌面/窄屏布局。
- 界面增加柔和反光、通透边缘和阴影；设置改成分组卡片与直接选择卡。
- 外观新增标准、大号、特大字号，尊重系统无障碍字号；保存进同一 SQLite 设置。
  用户明确不需要玻璃强度选项，因此没有添加该设置。
- Windows 使用随包附带的独立引擎进程；Android 接入 Chaquopy 嵌入式运行时。
- 随机回环端口、启动凭证、单数据目录进程锁、拥有者退出时停止引擎。
- 流式聊天、停止回复、保留请求 ID 的重试、历史分页、自定义风格、记忆更正/遗忘。
- 系统安全 Key 存储接入、完整 SQLite 备份与恢复、恢复前副本和损坏设置拒绝。
- 默认回复仍是离线规则演示；真实模型需用户配置 API 并授权，不是离线大模型。
- 本地应用不启动外部渠道和后台定时服务。Android 禁用系统云备份与自动设备迁移。

构建和使用方法见 [客户端说明](../clients/xinyu_flutter/README.md)。

## 0.2.0 交付时的产物与环境边界

| 层级 | 当前状态 |
|---|---|
| Windows 独立 Python 引擎 | 已打包并运行验收，用户无需安装 Python |
| Flutter 共享界面 | 静态分析通过，13 项测试通过 |
| Windows 完整图形程序 | 最终版本在当前电脑成功打开、连接本机引擎；设置分组、字号预览、保存和应用已实测 |
| Windows 安装向导 | Inno Setup 已成功生成 exe；本轮运行的是同构建的免安装程序，未逐页测试安装向导 |
| Android 独立 APK | ARM64 版本已构建，APK v2 签名与 16 KB ZIP 对齐检查通过 |
| Android ELF 静态检查 | 最终 APK 全部 76 个原生库为 ARM64，LOAD 段至少 16 KB 对齐，包括 Chaquopy 内层归档 |
| Android Keystore、FTS5、实际安装/启动/恢复 | 未在设备或模拟器运行验证 |
| 真实模型聊天质量 | 未调用模型，不做通过判断 |

### 0.2.0 历史交付文件

版本 `0.2.0+2`；应用源码提交 `7bd9831400bf485f80806456a6450385ed0e4fd3`。
当前电脑目录：`dist/xinyu-local/2026-09-25/`。

| 文件 | 字节数 | 用途 |
|---|---:|---|
| `XinYu-Windows-Setup.exe` | 33,164,915 | Windows 10+ x64 当前用户安装程序，无需单独安装 Python |
| `XinYu-Windows.zip` | 41,529,559 | Windows 免安装包，完整解压后运行 `XinYu/xinyu_flutter.exe` |
| `XinYu-Android-arm64.apk` | 47,056,040 | Android 7.0 / API 24 起，ARM64，开发签名测试包 |

同目录提供 `使用说明.md`、`SHA256SUMS.txt` 和 `build-receipt.json`。
下载归档及内部交付文件均已核对 SHA-256；交付文件的 SHA-256 为：

```text
f2efa38bf2dd2fea24bfcf3236e82b50086b25414ba558e9a1d7f2113e1d1c1b  XinYu-Windows-Setup.exe
90501b0c4b869d0051a1b57b02c37faf3889c6560b063a7f0c1556399aef51b6  XinYu-Windows.zip
391d50441640b6181a4c46efa0fe97b76f0b9de5f138cfb5b39a3fedf53a98e9  XinYu-Android-arm64.apk
```

Windows 完整包内含引擎，启动入口是 `xinyu_flutter.exe`。
随包引擎 SHA-256：`647637134ac32ff4d30077b5ab2bbc21161f24aebc30e00be10bca15c9eb0a62`。

Flutter 3.47.5 / Dart 3.13.4 已用于分析、测试与两端编译。本机没有 Visual Studio
C++ 工作负载，已改用 GitHub Actions Windows runner 构建；三个 Android 原生 wheel
在 Linux runner 从固定版本官方源码交叉编译，随后由 Windows runner 打包 APK。
完整依赖已解析，未替换为桌面 wheel、近似 tokenizer 或另一套记忆实现。

基础两端成功构建：[Actions 36129194053](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36129194053)。
最终界面构建：[Actions 36130724053](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36130724053)，三个打包任务全部成功。
[Windows 构建产物](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36130724053/artifacts/10861009659) /
[Android 构建产物](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36130724053/artifacts/10862285027)。
Actions 产物保留至 2026-10-02；上述本地交付文件不受该过期时间影响。
专用分支：`codex/local-apps-20260925`；没有合并到主分支或部署服务器。

## 0.2.0 历史验证

- `ruff check .`、`ruff format --check .`、`mypy companion_agent companion_memoryos` 通过。
- Python 全量回归：Windows **878 通过、1 失败、2 跳过**；
  最终源码的 Linux CI **877 通过、1 失败、3 跳过**
  （[Actions 36130724149](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36130724149)）。
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
- 界面更新后的 Flutter 分析、13 项测试通过；相关 Python 测试 23 项通过。
  包含字号保存、重启与备份恢复，以及再次打开设置时预览不重复放大。
- Linux 和 Windows 平台类型检查均通过。两端打包任务中的 Flutter 分析和 13 项测试均通过。
- 最终 Windows 图形程序在合成目录启动，实际打开设置、切换外观页、选择大号并保存；
  主界面字体随之放大，独立只读检查确认同一个 SQLite 设置保存为 `large`。
  测试窗口正常关闭后，其图形进程及子引擎均已退出；未关闭用户正在操作的早期预览窗口。
- 所有主动测试使用合成数据。未访问日常聊天库；没有发起真实模型调用。
- 新界面按真实 Flutter 组件渲染了桌面和手机静态预览。截图不作为 Android 设备运行证据。

实际进程运行 ID：

| 运行 ID | 结果与覆盖 |
|---|---|
| `native-bundle-9afb871faf4d4e6a9f16dcb88f5ce487` | 第一轮 Windows 冻结引擎通过，界面未验收 |
| `native-bundle-10c893a507f940298d16ca396767ec9a` | 加入损坏设置拒绝后的冻结引擎通过，界面未验收 |
| `native-bundle-b12fa65dab664680be00d21234f972c9` | Actions 首个 Windows 完整包的引擎验收通过 |
| `windows-ui-b90c2d0b50574fad8368e3195707c960` | 首个 Windows 完整包在本机显示玻璃界面、连接引擎；用户开始操作后停止自动控件输入 |
| `native-bundle-ce4d63fc9c1e45db92eafb942db81b16` | 最终 Windows 完整包的冻结引擎验收通过，包含字号设置重启和备份恢复 |
| `windows-ui-d4b8f4b2ae7e4003ba2a56a3dcc402f0` | 最终 Windows 图形界面、设置切换、字号预览与保存通过；仅使用合成数据 |
| `github-36130724053` | 最终 Android APK 76 个 ELF 原生库静态检查通过；不是 Android 运行验收 |
| `android-wheels-b68bdb6383d141de96402cbea9eb9abf` | Linux 交叉编译三个 ARM64 wheel，ELF 对齐通过 |
| `2e47a578-2565-4df0-bc24-a39a58dfdfcb` | 原应用生命周期场景通过 |
| `d843d5b1-0fa0-4798-89a6-98105df77e28` | 聊天流程通过；语言质量因未授权真实模型而 blocked |

本机运行数据和原始报告位于各自 `.agent-tests/<运行ID>`，不提交到仓库。
Actions 运行的冻结引擎报告随其构建产物保存。

## 后续构建入口

本地脚本为 `clients/xinyu_flutter/tool/build_local.ps1`，Android 原生依赖脚本为
`clients/xinyu_flutter/tool/build_android_wheels.py`。

另外已准备 [GitHub Actions 构建流程](../.github/workflows/local-apps.yml)：
Linux 生成 Android 原生 wheel，Windows runner 分别打包桌面和手机程序；
只生成可下载的构建产物，不发布 Release、不部署服务、不连接真实模型。
用户已授权上传专用分支和运行 Actions，现已完成上述构建。Android 产物采用开发签名，
仍需后续正式签名与手机验收；构建通过不能替代实际设备验证。
本分支配置为仅手动运行，代码推送不自动触发安装包构建；
2026-09-26 用户已明确同意与 0.2.8 源码一并上传此配置。

## 保留的失败证据

- `36127736866`：Flutter 源码缺少版本标签，SDK 被识别为 `0.0.0-unknown`；后续补取官方标签。
- `36128367201` / `36128813032`：Windows 已成功，Android 被 Flutter 自动添加的 32 位 ABI 阻塞；
  后续明确清空默认过滤器、限定 ARM64，并启用 AGP 9 内置 Kotlin。
- `36129194053`：两端基础包均成功。后续界面修改单独提交、重新构建。
- `.agent-tests/ui-watery-preview/capture-attempt-shadow-cleanup-failed`：截图辅助程序未恢复
  Flutter 阴影调试变量而触发清理断言；修正辅助程序后渲染通过，保留原失败记录。

构建成功不代表全部产品验收通过。既有遗忘回归、Android 设备运行和真实模型语言质量
仍需分别处理；这些边界没有通过跳过测试、替换断言或自动回退到演示模式来隐藏。
