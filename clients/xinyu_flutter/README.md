# 心隅 · Flutter 全玻璃原型

这是供 Windows / Android / iOS 后续迁移评估使用的客户端原型。保留原有 Python
记忆引擎及网页应用，客户端单独位于此目录。不是完整移动产品，也不宣称达到苹果
Liquid Glass 的光学效果。Windows 和 Android 的构建、测试结果见
[验证记录](../../docs/FLUTTER_PROTOTYPE_VALIDATION.md)。

## 已实现

- 自适应桌面侧栏 / 手机抽屉、虚拟化长对话列表、多行输入、中文输入法支持。
- 真实背景模糊的侧栏、顶部、消息气泡、输入框和设置弹窗。
- 同一平面内不重叠的玻璃区域使用 `BackdropGroup` / `BackdropFilter.grouped`；
  弹窗与抽屉独立分组，避免对重叠表面错误复用模糊结果。
- 静态背景单独绘制和隔离重绘；流式文本更新合并为最多约每 32ms 一次。
- 自带明确标记的示例对话和示例回复。演示数据只在本次运行内存中保留，不调用模型。
- 连接已有本地后端：读取设置、创建会话、分页历史、NDJSON 流式回复、失败重试。
  重试沿用同一个 request_id，避免重复写入；保存设置保留未在原型展示的后端字段。
- 右上角速度表按钮：开关帧耗时面板、清空统计、载入 200 条示例消息。

## Windows 运行

构建后可运行仓库根目录的 `start-flutter-prototype.ps1`，或直接打开
`dist/xinyu-flutter/windows/xinyu_flutter.exe`。旁边的 `data` 和 DLL 必须一同保留。
启动默认进入演示空间，不自动读取原网页数据库。

需要接入真实引擎时，另开终端运行仓库根目录的：

```powershell
.\start-flutter-backend.ps1
```

原型后端监听 `http://127.0.0.1:8766`，使用独立的 `.agent-data/flutter-prototype`
目录。客户端「陪伴设置 → 连接与数据 → 连接服务」后，核对本地保存与消息处理选项并保存。
可以先使用离线规则回复验证流程，再自主选择 DeepSeek。

原型沿用现有根页面 Cookie 握手和请求头，不改动后端的回环监听、TrustedHost、
Origin 校验及同意检查。客户端仅接受回环 HTTP 地址，禁止重定向。API Key 只在会话
内存中使用；不写入客户端配置。没有把后端直接暴露到局域网或公网。

## Android

安装生成的 `dist/xinyu-flutter/xinyu-prototype.apk` 后可以独立体验演示界面。
此 APK 使用开发签名，仅用于原型测试，不是应用商店发布包。

连接电脑上的本地记忆服务时，用户先在已授权的 Android 调试设备上配置 USB 转发：

```powershell
adb devices
adb reverse tcp:8766 tcp:8766
```

手机应用仍连接 `http://127.0.0.1:8766`。拔掉 USB 后应回到演示，或重新连接服务。
这不是手机内置 Python 引擎，也不是远程账号服务。Android 仅允许回环地址的明文 HTTP。
ADB 设备授权和安装确认由用户完成。

## iOS

已生成 iOS 工程并共享客户端代码。必须在 macOS + Xcode 中完成构建、签名和真机测试。
此轮 Windows 环境没有编译或验证 iOS。iPhone 真机目前以演示模式评估界面；没有
提供 iPhone 到电脑服务的网络连接方案。iOS 模拟器可在后续 Mac 环境中测试本机后端。

## 构建与测试

使用 Flutter 3.47.5 / Dart 3.13.4；依赖版本由 `pubspec.lock` 固定。
Windows 需 Visual Studio C++ 桌面编译工作负载、CMake 和 Windows SDK；
Android 使用 JDK 21、Android SDK 36、Build Tools 36。

Windows 下中文项目路径可能触发 Dart LSP 和 Android 路径检查问题。
`tool/build.ps1` 将源码复制到单独英文路径构建，再把产物复制回仓库 `dist/`。
只复制，不镜像删除。不要同时在同一构建目录运行多个 Flutter 构建或测试命令。

```powershell
# 在本目录运行；将 FlutterSdk 换成实际安装位置。
.\tool\build.ps1 -Target test -FlutterSdk D:\Tools\xinyu-sdk\flutter
.\tool\build.ps1 -Target windows -FlutterSdk D:\Tools\xinyu-sdk\flutter
.\tool\build.ps1 -Target android -FlutterSdk D:\Tools\xinyu-sdk\flutter `
  -AndroidSdk <Android-SDK目录> -JavaDirectory <JDK目录>
.\tool\build.ps1 -Target profile -FlutterSdk D:\Tools\xinyu-sdk\flutter
```

在没有中文路径问题的工作目录也可直接：

```text
flutter pub get
flutter analyze
flutter test
flutter run -d windows
flutter run -d <Android设备ID>
```

`tool/live_backend_smoke.dart` 是端到端接口测试，必须使用**新建的可丢弃数据目录**：

```text
python -m companion_agent.app --port 8767 --data-dir .agent-data/flutter-smoke
dart run tool/live_backend_smoke.dart http://127.0.0.1:8767
```

测试会临时启用离线回复和保存选项，在独立测试库创建合成对话，最后还原设置。
不要将它指向正在使用的真实数据服务。

## 性能记录的含义

性能面板记录最近 600 帧的 build / raster P95，以及两者较大值超过 16.67ms 的帧数。
这不是显示器实际 FPS，也不是 GPU 呈现完整延迟。面板每秒最多刷新一次，避免自发重绘循环。
正式比较使用 profile / release 模式，关闭面板后用 integration_test 采集。

`integration_test/glass_performance_test.dart` 覆盖 200 条消息的滚动、多行输入和
4 次设置弹窗开合。`XINYU_MAXIMIZED=1` 可让 Windows 测试窗口最大化；输出位于
构建目录 `build/integration_response_data.json`。手机要单独测试键盘、手势、功耗和持续发热。

## 未包含的产品功能

手机端独立记忆引擎、跨设备同步、登录、多用户隔离、推送、语音、相机、应用商店签名发布，
以及网页已有的记忆编辑、MCP 和定时任务面板，均不属于此原型。当前 API 模型参数沿用
后端设置；界面只提供模式和 Key 输入，没有迁移所有高级选项。

## 文件组织

`lib/data` 定义与实现接口；`lib/state` 管理会话和帧统计；`lib/ui` 是玻璃组件与页面。
后续决定端侧或服务端架构时，可替换 repository，而不必重写聊天页面。
