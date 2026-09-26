# Android 发布包启动修复

日期：2026-09-25。用户在红米 K50 安装 0.2.0 后看到“本机引擎未连接”和
“操作未完成，请检查本地服务后重试”。手机运行的是 APK 内置引擎，不需要启动电脑服务。

**当前结论：** `0.2.1+3` 候选 APK 已构建，桥接和 FTS5 内容检查通过；
实际 Android 启动/重启尚未通过验收。测试驱动冷启动等待问题已在本地修复，
本地 3 项驱动回归通过，等待用户审阅后授权上传及复测。没有再次补发微信。
用户新增要求：先完成本地检查/测试并展示结果，明确同意后才能上传 GitHub 或发起新构建。

## 已确认的问题

旧 APK 的 SHA-256：
`391d50441640b6181a4c46efa0fe97b76f0b9de5f138cfb5b39a3fedf53a98e9`。

Python 在 `AndroidCredentialStore` 初始化时通过 `java.jclass` 查找
`com.xinyu.xinyu_flutter.DeviceCredentials`。Flutter 的 release 构建开启 R8，
但这个类只有 Python 字符串引用，旧构建没有保留规则。
检查实际 APK 的全部 DEX 类定义，目标类不存在；不是仅检查源码或 Debug 构建。
这会阻断启动，即使用户尚未配置 API Key 也会发生。

旧 APK 的 `libsqlite3_python.so` 为 SQLite 3.50.4，但没有编译 FTS5。
同一个记忆数据库初始化时会创建 FTS5 虚拟表，因此桥接修复后还需补齐这一依赖。
此项最初由发布包 ELF 内的编译选项与模块内容检查发现，运行验证单独记录。
随后在 Android 15 模拟器安装仅修复桥接的实际 ARM64 发布包，界面显示 A03；
诊断栈定位至 `Database.initialize()` 执行建表脚本，确认启动已越过桥接阶段、
仍在数据库初始化失败。运行 ID：`android-startup-1826d5746c664e91a656f338c4fc6207`。

另一个问题是 Kotlin 返回的 `PlatformException` 没有转换为客户端可识别的启动异常，
因此真正的启动失败被显示成“检查本地服务”通用提示。

反射引用需要显式保留的原理见
[Android 官方 R8 说明](https://developer.android.com/topic/performance/app-optimization/keep-rules-overview)。

## 修复

- 仅为 `DeviceCredentials` 及其成员添加 R8 保留规则，保持全局压缩优化。
- 构建后解析实际 APK 的 DEX，检查桥接类及构造器、读取、保存、删除方法都仍可调用。
  缺少任何一个就使构建失败。
- 安卓启动失败按运行环境初始化、组件加载、引擎启动分别显示 A01/A02/A03。
  不把异常原文、路径、聊天或 Key 输出到界面和诊断日志。
- 新增隔离模拟器验收：安装实际 ARM64 release APK，确认界面已连接引擎，
  停止应用后再次启动并确认连接。只允许 Actions 中新建的模拟器和空白安装。
- 从固定校验值的 SQLite 3.50.4 官方源码构建同名原生库，保留原版本、文件格式和
  CPython 绑定，启用 FTS5 与 16 KB 对齐。发布包检查同时确认 FTS5 被实际打入 APK。
  未引入第二套数据库，也未替换为简化搜索。
- Chaquopy 17 生成 JNI 库后，仅移除当前构建目录内的简化 SQLite 副本，
  让 CMake 编译的 FTS5 版本成为唯一同名输入；保留默认重复文件报错，
  不依赖顺序不确定的 `pickFirsts`。不会修改下载缓存或用户数据。
- 版本升为 `0.2.1+3`。玻璃效果和设置布局没有再改动。

## 验证状态

源码提交：`f5c2dd968dad7247b12fb66ba48f9eabb62fc831`。
构建：[Actions 36140626506](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36140626506)。

- 原 APK 的新增桥接检查失败，证明检查能捕获本次已发出的缺陷。
- Flutter 分析、14 项测试通过，新增测试验证安卓原生异常正确呈现且不泄露异常内容。
- Ruff、格式检查和 mypy 通过。加入驱动回归后的最新 Windows Python 全量结果为
  **881 通过、1 失败、2 跳过**（175.06 秒）；
  失败仍是原有的 `test_natural_location_forgetting_deletes_raw_sources_even_without_memory_card`。
  测试要求来源轮次标记为 `forgotten`，实际仍为 `active`，没有为变绿修改删除语义或断言。
  本轮结果保留为 `local-final-regression.xml` / `.log`；先前 878 通过的结果也保留。
- 候选 APK 构建、R8 桥接方法、FTS5 内容、APK v2 签名和 16 KB ZIP 对齐检查通过。
  下载归档校验通过；本机重新检查相同 APK 的桥接、FTS5 和全部 76 个 ARM64 ELF
  原生库的 16 KB LOAD 段对齐，均通过。
- Android 15 启动任务失败，运行 ID `android-startup-887f6053f39e43c69d88d051d4d53f4d`。
  `am start -W` 在 10.99 秒报告 `Status: timeout`，测试驱动直接退出、停止应用，
  尚未进入原本的 150 秒界面等待。日志显示应用活动仍在重建、Python/SQLite 库已加载，
  没有本次引擎连接成功证据，也不能将缺少错误栈解释为启动通过。
- 本地修正驱动：命令明确报错仍失败；短暂首帧超时及初始化中的“未连接”标题继续等待，
  两次启动都必须实际出现“记忆保存在本机”，超时仍失败。3 项回归覆盖冷启动短暂超时、
  永久未连接、启动命令错误；`tests/test_android_startup_driver.py` 全部通过。
  这些是合成的驱动单元测试，不是 Android 实机或模拟器运行通过。
- 红米 K50 真机回归：尚未完成。未调用真实模型。

原包失败证据与本轮本机检查保留在 `.agent-tests/android-startup-regression/`。
模拟器报告独立保存，不将静态检查或 Windows 测试冒充 Android 运行通过。

## 候选安装包与下一步

本机文件：`dist/xinyu-local/2026-09-25-0.2.1/XinYu-Android-0.2.1-arm64.apk`，
47,547,700 字节，SHA-256：
`88e80d98e50aa950264cead86cced0b12804e2c400a82e7085a3a33241f1e555`。
已启动构建留下的
[GitHub 产物](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36140626506/artifacts/10866598385)
也为同一个候选包。该构建在用户提出新上传约束之前已启动，之后只读取结果。

新旧 APK 的开发签名证书不同，无法直接覆盖安装；卸载会清除应用私有数据。
此候选包尚不作为已完成运行验收的替换版本推荐。玻璃界面、分组设置、字号保持现有设计。

本机目前没有配置可运行该 APK 的 Android 测试环境。若用户同意上传已在本地检查的
测试驱动和手动打包配置，可用 `target=android-startup`、`artifact_run_id=36140626506`、
`api_level=35` 复用现有 APK，仅执行启动与重启验收，不重新编译安装包。
取消推送自动打包的配置及本报告仍保留在本地，等待用户确认上传。

## 保留的修复中间结果

- `36137629012`：桥接修复后的 APK 已构建；Android 11 模拟器未进入主界面，
  原日志只包含 Java 错误标签，不能据此判断退出原因。运行 ID：
  `android-startup-3786d1f7d152422a899495e44fe38ccb`。
- `36139482106`：复用上一个 APK、增加原生崩溃日志并在两个 Android 版本诊断。
  Android 15 明确显示 A03，栈指向数据库初始化。该 APK 未包含 FTS5 修正。
  Android 11 的失败栈为 `libndk_translation.so` 的 SIMD 指令解码 SIGILL，
  属于该模拟器 ARM 转译环境的运行限制；它不能代表 ARM64 真机兼容性结果。
  该失败记录保留为 `android-startup-d2ef08831855425cb78cb2ebe4c0373c`，未记作通过。
  后续默认在 Android 15 安装同一个 ARM64 发布包，API 30 保留为手动诊断选项。
- `36138695724`：首次 FTS5 构建遇到 Windows 路径反斜杠被 CMake 当作转义符。
  构建失败、没有交付 APK；提交 `d84f4f6` 将传入的源码路径规范为正斜杠后重新构建。
- `36139450629`：APK 编译及签名成功，但内容检查检测到打包器选回了不含 FTS5
  的依赖副本，构建被拦截，没有交付该 APK；随后移除 `pickFirsts` 并明确唯一输入。
