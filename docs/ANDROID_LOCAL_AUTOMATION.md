# 本机 Android 自动化测试

本机使用独立 Android 15 模拟器运行交付的 ARM64 Release APK。脚本每次创建新的
AVD 和应用数据，检查模拟器进程、AVD 名称及 ARM64 ABI，不附着到已有设备。
截图、界面树、持续 logcat 和结构化结果写入 `.agent-tests/android-local-<id>/`。
运行结束关闭自己启动的模拟器；AVD 文件保留在指定工作目录供排查。

2026-10-18 完整运行 `android-local-f42b6ca6081d4f5684d8572b3065bae3`：37 项通过、
0 项失败。测试对象为 0.2.27+30，APK SHA-256
`0e62f471bea12d7fc928239efbf4528da4b72d631071d049ae941343bb582603`。
本地完整报告为 `.agent-tests/android-local-f42b6ca6081d4f5684d8572b3065bae3/report.md`。
旧失败运行的日志和截图保留，已关闭的旧 AVD 可清理以回收空间。

## 当前电脑的环境

- Windows WHPX 已启用；Android Emulator 37.2.12，Google APIs API 35 x86_64 r9。
- 模拟器实际报告 `x86_64,arm64-v8a`，直接安装交付 APK，未替换 APK 的原生库。
- SDK 位于 `E:/XinYu-Dev/xinyu-sdk/test-sdk`，AVD 工作目录为 `E:/XinYu-Dev/xinyu-sdk/test-avds`。
- 使用宿主 GPU 并关闭 Vulkan。初次使用 SwiftShader 时 Windows 记录 QEMU
  `0xc0000005` 崩溃；切换图形后端后冷启动及重启检查通过。
- 官方下载文件及校验回执保存在 `E:/XinYu-Dev/xinyu-sdk/android-test-downloads/verified.json`。
- 本机测试记录和交付包分别存放在 `E:/XinYu-Dev/project-tests` 和
  `E:/XinYu-Dev/releases`；仓库内 `.agent-tests`、`dist` 为兼容目录链接。
  运行本机测试前，在同一个 PowerShell 会话中执行
  `. ./.agent-tests/use-e-test-env.ps1`，使 Python、Flutter 的临时文件也写入 E 盘。
  该本机会话同时设置 `FLUTTER_ROOT`、`XINYU_BUILD_ROOT` 和 Android wheels 路径；
  `build_local.ps1 -Target test` 使用 E 盘的新目录，仅分析与运行 Flutter 测试。
  构建脚本仍支持显式 `-BuildRoot`，未配置环境变量的其他电脑保留原默认值。

## 测试方式

`tool/smoke_android_local.py` 使用 ADB 操作实际 Flutter 页面，检查真实本机引擎握手，
并执行冷启动、强制停止后重启、手机和网易云连接、权限说明及系统授权往返。

`tool/android_probe/` 是单独的测试 APK 源码，不进入心隅安装包。它与本地测试版使用
同一调试签名，通过 Android Instrumentation 调用已安装 APK 的 Python/JNI/MCP 代码。
检查原生依赖、工具发现、音量确认和去重、权限撤销、亮度和勿扰的系统读回，
以及合成测试页面上的无障碍读取、点击、输入与密码遮罩。

系统授权只在该新建模拟器中设置。探针的原生调用是确定性测试输入，没有模型调用。
网易云检查包含工具目录和无播放器时的失败处理，真实账号登录、点歌和播放另行验收。
这不替代实体手机的厂商权限、后台保活和性能测试。

## 重跑

在仓库根目录执行。构建探针时，`--output` 必须是不存在的新目录：

```powershell
$sdk = 'C:/Users/Admin/.cache/chu-men-bie-wang-android/sdk'
$java = 'C:/Users/Admin/.cache/chu-men-bie-wang-android/jdk21/jdk-21.0.12+8'
. ./.agent-tests/use-e-test-env.ps1
$probe = 'E:/XinYu-Dev/xinyu-sdk/probe-builds/' + [guid]::NewGuid().ToString('N')
.venv/Scripts/python.exe clients/xinyu_flutter/tool/build_android_probe.py --sdk $sdk --java-home $java --output $probe --keystore C:/Users/Admin/.android/debug.keystore
if ($LASTEXITCODE -ne 0) { throw '探针构建失败' }
.venv/Scripts/python.exe clients/xinyu_flutter/tool/smoke_android_local.py --sdk E:/XinYu-Dev/xinyu-sdk/test-sdk --adb E:/XinYu-Dev/xinyu-sdk/test-sdk/platform-tools/adb.exe --avd-workspace E:/XinYu-Dev/xinyu-sdk/test-avds --apk dist/android-0.2.27-preview/XinYu-Android-0.2.27-Preview.apk --probe-apk "$probe/xinyu-native-probe.apk"
```

当前入口仅接受测试包 `com.xinyu.xinyu_flutter.preview`。省略 `--probe-apk` 时只运行
启动和界面测试，不能据此宣称原生功能通过。不能通过设置 `GITHUB_ACTIONS=true`
绕过原 CI 测试入口的环境限制；本机测试使用独立入口。
