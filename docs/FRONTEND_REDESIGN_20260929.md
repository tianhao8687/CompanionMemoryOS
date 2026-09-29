# Android / Windows 前端改版

日期：2026-09-29。Flutter 3.47.5、Dart 3.13.4、Windows 本机环境。
按最终确认的原型完成 `clients/xinyu_flutter`，源码版本为 `0.2.10+13`。
本轮本地 Android 打包未成功，Windows 缺少编译工具；没有发布或生成新安装包。

## 本次实现

- Android 单列聊天和抽屉会话列表；宽度达到 880 时切换为 Windows 双栏。
  桌面聊天阅读区域最大宽度为 1040，输入区域随聊天面板展开，左右各留 14 像素。
  侧栏按窗口宽度的 22.5% 分配，限制在 252 至 356 之间；支持按标题筛选、创建与切换会话。
- 暖白背景、雾蓝发送气泡、暖白接收气泡与深灰正文，统一已有的背景模糊、白色高光边缘和柔和阴影。
  以默认实色背景 `#f7f6f4` 为参照，正文与背景对比度约 14.96:1，辅助文字约 4.56:1；
  这不是对任意用户自定义背景或所有控件状态的完整无障碍认证。
- 标题移除“AI 伙伴”副标题。新增 24 字备注名和 200 字私人备注，支持保存、取消和清空。
  Windows 名称旁提供入口；Android 可长按名称，或从角色主页进入。
- 备注通过既有 `/api/settings` 写入原有 SQLite 设置；重启后保留。
  `companion_name` 仍是角色原称呼；备注不参与人物版本、角色规则或记忆身份。
- 对方连续消息共用头像，真实消息时间在分段处显示；图片独立于文字气泡显示。
  保留模型原有段落和消息 ID，不用前端改写回复内容。
- 桌面 Enter 发送、Shift + Enter 交给文本输入处理换行；组合输入期间不发送。
  手机保留多行输入与发送按钮。表情插入光标位置，不自动发送。
- 原有引用、收藏、多选、停止回复、图片导入、草稿、分页和阅读位置保持继续可用。
- 按后续确认移除聊天界面的发送快捷键说明、示例/离线模式提示、输入占位文案和空白会话引导。
  输入工具按钮与发送按钮统一为 40 逻辑像素的圆形视觉区域、20 像素图标，保留至少 48 像素点击区域。
  输入框内层四周留 8 像素，玻璃外沿再留 6 像素；工具按钮之间留 4 像素布局间隔。
- 气泡使用独立 `MessageSurface` 组件：16 像素圆角、半透明浅色与轻微明暗过渡、背景模糊，
  配合单层细边缘与很淡的短阴影。浅雾蓝区分自己的消息，浅白区分对方消息。
- 以用户再次指定的 Windows 概念图为基准：桌面保留一体化圆角玻璃顶栏、柔和的蓝灰与暖色背景层次，
  输入框使用外层玻璃与内层细边缘。Android 背景保持浅色，顶栏透明，不增加方形衬底。
  桌面正文为 19 像素、手机为 16 像素；桌面顶栏头像 56、消息头像 48，侧栏头像 52。
  桌面聊天图片最大 320×240、手机最大 240×180；窄布局按可用宽度等比例收缩。
  引用内容与待发送引用均取消深色竖线，改用浅色衬底；引用气泡按内容宽度布局，仍可点击查看原文。
- 收尾统一设置、角色主页、手账、收藏、记忆、上下文、表情库及错误弹窗的蓝灰玻璃颜色。
  设置页标题简化为“设置”，移除角色页装饰性标语；仍保留必要的功能、权限和错误说明。
  Windows 安装器默认版本号同步到 `0.2.10`，打包流程仍只接受手动触发。

## 验证结果

| 检查 | 结果 |
| --- | --- |
| `flutter analyze` | 通过，零问题 |
| `flutter test` | 推送前补充启动标识验证后，58 项全部通过 |
| 实际 Flutter 渲染 | 390×844、1586×992 主界面，双方气泡组件，备注、设置和角色主页已渲染；仅合成数据 |
| 小屏 / 大字号 | 320×640 + 键盘 + 1.5 倍字号；880、1024、1440 宽长备注通过 |
| 备注设置与角色相关 Python 测试 | 28 项通过，包括保存、重启、清空和人物规则不变 |
| `ruff check .` | 通过 |
| `mypy companion_agent companion_memoryos` | 通过，126 个源文件 |
| 全量 Python 测试 | 后续修复测试同步和旧版夹具后，1155 项通过、2 项跳过 |
| Windows 原生 profile / 窗口测试 | 未完成；本机未安装 Visual Studio C++ 工具链，未产生本轮安装包和原生性能数据 |
| Android 本地 release 构建 | Java 通信初始化问题已修复；NDK 下载持续超时后停止，未生成 APK |
| Android 真机 | 未连接设备，未验收 |

键盘单元测试验证 Enter 只提交一次及组合输入不提交。Widget 测试没有系统文本输入后端，
Shift + Enter 后通过模拟文本输入事件验证多行内容；这不能替代 Windows 中文输入法真机验收。

初次全量测试中的既有失败（后续已修复测试）：

- `test_blended_memory_repairs.py::test_semantic_raw_evidence_survives_new_conversation_and_restart_without_extraction`：
  向量索引表数量预期 2，实际 1。
- `test_database_migration.py::test_v5_database_adds_companion_experience_storage`：
  旧版迁移测试删除表时，`invalidate_turn_passages` 触发器仍引用该表。

在独立 Python 测试进程中加载 HEAD 的 `companion_agent/romance.py`，即不含本次备注字段的版本，
两项均以相同原因失败；对照时未修改工作区文件。

后续排查确认两项均为测试本身未跟上实现：索引测试在异步索引完成前读取表数量，
迁移夹具从新表结构构造 v5 数据库时遗漏了新版段落索引及失效触发器。
现在索引测试在有限时间内等待真实后台线程完成，并核对两个用户消息的精确索引 ID，
重启前后均关闭自己的后台索引器；迁移夹具先移除当时尚不存在的表与触发器。
没有改变生产检索、SQLite 迁移或消息处理逻辑，也没有放宽原有验收目标。
两份测试文件共 28 项通过；全量重跑为 **1155 passed, 2 skipped**（286.06 秒）。
最终证据为 `dist/frontend-final-20260929/checks/pytest-repaired.log`，初次失败日志保留。

## 真实本地服务联调

均使用 `ManagedInstance` 创建独立合成目录，结束后停止自己的子进程；未读取日用聊天数据库。

- 运行 ID：`c5b17c16-d155-4b5f-9a60-11392dbe099a`。Flutter 的实际 `LocalRepository`
  验证页面握手、设置与备注读写、离线流式回复、历史持久化和同请求重放；全部通过。
  证据保存在该运行目录的 `flutter-smoke.json`。
- 运行 ID：`b4ba7436-f9cb-4b12-b416-81f958914c50`。按项目规定运行
  `tests/scenarios/chat_quality.json`，后端流程通过，语言质量状态为 blocked。
  本轮没有获授权的真实模型批次，离线结果不证明模型表达质量。
- 最终收尾复测 ID：`4a27a38e-caa4-4e1a-8696-79e4833aec2f`。上述 Flutter `LocalRepository`
  握手、设置、备注、流式回复、持久化及幂等重放再次全部通过。
- 最终场景复测 ID：`b69d9335-67eb-4dbb-96f5-fa579dbefcdd`。`chat_quality.json`
  后端通过，语言质量 blocked，命令按预期返回 2；未发起真实模型调用。

保留运行目录中的通过与失败证据；不将原始提示、数据库和截图加入源码提交。

## 查看与复现

本机最终组件渲染输出位于 `dist/frontend-final-20260929/`：`windows.png`、`android.png`、
`windows-remark.png`、`message-components.png`，以及 `windows-settings.png`、`android-settings.png`、
`windows-profile.png`、`android-profile.png`。组件图使用生产界面的消息控件，包含双方短句、
长句和引用消息。这些是 Flutter Widget 客户区渲染与合成聊天，不是安装包真机截图。
主界面预览可读取独立的猫头像和花束素材，经正常 `LocalImage` / `ChatPhoto` 组件显示；
素材通过内置 imagegen 参照用户图片生成，只从预览入口传入，不加入生产默认会话或头像。
素材与完整生成提示保存在 `dist/frontend-20260929-reference-v2/assets/README.md`，保持 Git 忽略；
原生系统标题栏另需 Windows 验收。

按概念图调整整屏比例、玻璃材质与引用样式后再次通过 `flutter analyze` 和 57 项 Flutter 测试，
并重新渲染检查 Android / Windows 两种布局以及独立组件图。

在 Flutter 客户端目录执行：

```powershell
flutter test tool/layout_preview.dart --dart-define=XINYU_PREVIEW_DIR=<绝对输出目录>
```

如需与概念图相同类型的图片内容，另传
`--dart-define=XINYU_PREVIEW_ASSETS=<包含 avatar.png 与 flowers.png 的绝对目录>`。

预览入口只使用 `DemoRepository`。Windows 默认读取本机微软雅黑；其他主机可通过
`XINYU_PREVIEW_FONT` 指向可用中文字体。截图生成时启用真实阴影模糊，避免测试默认的
无模糊阴影造成视觉偏差。

## 最终本地构建记录

构建 ID：`80d96b72a31f4b648a0ec35a8f8dc4f5`。通过 `tool/build_local.ps1 -Target android`
在独立构建副本中再次完成依赖解析、零问题静态检查和 57 项 Flutter 测试。
Python 引擎已按当前源码暂存；SQLite 3.50.4 源码校验通过。

本机 Android SDK 36 / JDK 21 工具检查通过，但 Gradle 9.3.1 初始化进程通信时失败：
`java.io.IOException: Unable to establish loopback connection`，底层为 Java NIO Unix domain socket
的 `Invalid argument: connect`。IPv4、单次 daemon、较短临时目录和另一 Windows selector 的
局部诊断均未解决；未修改系统网络、防火墙或全局 Java 设置。没有生成 APK，也没有进行 APK
签名、对齐或真机验收。诊断结束时未发现仍运行的 Gradle daemon。

本机日志保存在 `dist/frontend-final-20260929/checks/`：`android-build.log`、
`android-build-ipv4.log`、`gradle-diagnostic.log`、`gradle-short-temp.log`、
`android-build-windows-selector.log`、`pytest.log`、`chat-quality.log`。
该次全量 Python 仍复现两项既有失败；后续修复与新结果见上文，失败记录保留。

### Java 通信恢复

后续最小 Java `Selector.open()` 自检发现：将 `java.io.tmpdir` 与
`jdk.net.unixdomain.tmpdir` 都设为仓库 `dist/java-tmp` 后，默认 `WEPollSelectorImpl`
创建成功。先前试用的短目录仍在 AppData 内，未避开宿主路径重定向；这一对照支持
临时目录重定向是本机触发原因的判断。

`tool/build_local.ps1` 已为 Android 构建加入这个进程范围的临时目录设置，并在 `finally`
恢复原来的 `JAVA_TOOL_OPTIONS`。可用 `-JavaTempDirectory` 指定短路径，不修改系统或 JDK 安装。
构建复测 ID：`aa93366ffd66414b988ca34e04a9f15a`。静态检查和 57 项 Flutter 测试再次通过；
Gradle daemon 已开始执行构建，并进入 NDK 28.2.13676358 安装阶段，原 Java 通信错误已消失。
日志为 `checks/android-build-recovered.log`。本机 NDK 下载持续超时；官方源分段下载也未完成，
尚未达到整包哈希校验阶段，未使用不完整工具包。已停止本次所属 Gradle 与下载进程，
保留下载分段、进度和原始失败日志。最终状态为 `checks/recovery-status.json`。

Windows 的微软 Build Tools 安装器签名有效，但当前执行身份没有管理员令牌。
可由用户在本机授予安装权限，或在明确批准推送后使用现有手动 GitHub Actions 流程。
安装权限要求见[微软安装文档](https://learn.microsoft.com/en-us/visualstudio/install/command-line-parameter-examples?view=visualstudio)。
用户随后明确批准推送当前改动并手动打包 Windows / Android。打包仍保持手动触发。

推送前同步更新 Android 启动验收：旧脚本依赖已移除的“记忆保存在本机”可见文案，
现改为消息输入框的非可见语义标识 `xinyu-local-ready`；只有真实仓库完成连接时才出现。
不增加界面提示，演示、加载中或连接失败均不满足验收条件。Widget 测试验证这些状态；
Android 驱动检查本应用、启用状态和精确资源 ID，7 项驱动测试通过，普通文本不能冒充连接成功。

推送 GitHub、上传产物或再次运行 GitHub 打包流程仍需用户明确批准；安装包打包保持手动。
