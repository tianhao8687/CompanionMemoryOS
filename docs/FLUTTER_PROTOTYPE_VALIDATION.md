# Flutter 全玻璃原型验证

日期：2026-09-24。源码分支：`codex/flutter-glass-prototype`。
Flutter 3.47.5 / Dart 3.13.4 / Windows 11；这是原型验证，不是跨设备性能保证。

## 完成的检查

- `flutter analyze`：零问题。
- `flutter test`：10 项通过。包含 320×640、390×844、1920×1080 的聊天与设置布局；
  软键盘及 1.5 倍字号；演示流式回复；修改称呼；200 条消息懒加载；失败重试复用 ID；
  完成结果后断线不误报失败；保留后端未知配置；回环地址限制；Cookie / 请求头 / 跨块 UTF-8。
- Windows release 编译成功；实际桌面窗口检查了初始界面、最大化和设置弹窗。
- `flutter drive --profile`：窗口与最大化场景均通过滚动、输入和弹窗测试。
- Android release APK 编译成功，开发签名；`aapt dump badging` 确认应用标识
  `com.xinyu.xinyu_flutter`、最低 API 24、目标 API 36、名称「心隅 · 原型」。
- 真实 Python 后端联调：单独测试目录、离线模型下，握手、设置、NDJSON 流式响应、
  历史持久化和同一 request_id 重放通过。没有调用付费模型或使用原网页记忆数据。
- PowerShell 启动 / 构建脚本语法检查通过；生成目录、凭据配置、数据库和产物不加入源码。

## Windows 渲染采样

场景：200 条示例消息，8 次快速滚动，输入文字，4 次打开 / 关闭玻璃设置弹窗。
性能面板关闭。表中尺寸是 Flutter 实际内容区域，不含系统边框。

| 指标 | 窗口 1264×821 | 最大化 2560×1369 |
| --- | ---: | ---: |
| 采样帧数 | 506 | 507 |
| 构建耗时 P95 | 0.340 ms | 0.328 ms |
| 光栅耗时 P95 | 3.197 ms | 3.687 ms |
| 构建或光栅超过 16.67 ms 的帧数 | 1 | 1 |
| 设备像素比 | 1.0 | 1.0 |

摘要：[窗口](validation/flutter-windowed-performance.json)、
[最大化](validation/flutter-maximized-performance.json)。原始 Flutter timeline 保存在本机
`dist/xinyu-flutter/windowed-profile.json` 和 `maximized-profile.json`，没有加入 Git。

这些数字是 Flutter `FrameTiming` 的构建和光栅阶段耗时，不等于显示器实际 FPS、
完整呈现延迟或输入延迟。没有采集旧网页相同条件下的基线，所以不声称提升了多少倍。
单机短时测试也不能代替手机功耗、持续发热、不同显卡 / 分辨率的测量。

Windows 上 `integration_test` 提示未检测到原生插件；本轮使用 `flutter drive` 的
VM 服务数据通道，测试退出成功并确实产生了完整 timeline 与摘要。没有据此宣称
Android instrumentation 或 iOS XCTest 已通过。

## 交付与限制

- Windows：`dist/xinyu-flutter/windows/xinyu_flutter.exe`，必须与同目录 DLL / data 一起使用。
- Android：`dist/xinyu-flutter/xinyu-prototype.apk`，仅用于测试，不是商店签名发布包。
- APK SHA256：`51AA61B4CD4A8E8D5AAA782E7E25EDA856A02791EF503CF2E0398CA8E22D72D9`。
- 测试时没有连接 Android 设备，因此未验证真实手机的帧率、键盘行为或 USB 联调。
- iOS 只有工程和共享界面源码；本轮没有 macOS / Xcode，未构建和真机验收。
- 默认演示模式独立运行。真实记忆功能依赖电脑上的 Python 服务；原型尚未将引擎移植到手机。
- 原网页的 `companion_agent/web`、后端安全策略和真实数据库未修改。
- 运行和构建命令见 [原型说明](../clients/xinyu_flutter/README.md)。

## 实现取舍

保留真实背景模糊：同平面不重叠的玻璃采用分组取样，弹窗 / 抽屉独立分组；
聊天列表按需构建；流式更新限频；静态背景隔离绘制；超宽屏阅读区最大 1040 逻辑像素。
手机使用抽屉和随软键盘缩放的输入区域。帧统计面板只在开启时每秒刷新，避免它自身
造成持续重绘。原型没有通过自动关闭玻璃或降低分辨率来取得这些数据。

构建环境补充了独立的 Flutter SDK，以及现有 Visual Studio 的 C++ 工作负载 / CMake。
使用独立英文路径构建副本，规避当前 Dart LSP 对中文项目路径的错误；不移动原项目。
