# 心隅 0.2.31 · Windows / Android 本地语音与手机陪伴

2026-10-19 发布 Windows，2026-10-20 补充 Android。版本 `0.2.31+34`，发布标签 `xinyu-v0.2.31`。
[下载本版](https://github.com/tianhao8687/CompanionMemoryOS/releases/tag/xinyu-v0.2.31)。

## Windows 更新

- 新增「说给我听」：免费开源 sherpa-onnx / Zipformer 在本机识别普通话与英语。
  首次主动下载约 190 MiB 资源，无需额外语音账号、API Key 或语音服务器；录音不上传、不保存。
  转写可以编辑，点「放进输入框」后仍由用户手动发送，保留原草稿和会话变化保护。
- 打开语音面板时预加载已下载模型，同面板继续说话复用模型。首次加载期间也可以开始收音，
  开头音频有界暂存，模型就绪后按顺序处理。已验证且未改变的资源复用私有校验记录。
- 关闭面板、切后台和内存压力会释放资源；下载、权限、取消和识别失败都有明确状态，
  不自动下载、不回退收费语音服务。聊天回复仍沿用用户自行配置的聊天模型及其费用规则。
- 保留 0.2.26 的 Windows 网易云后台点歌、歌单读取、音乐品味及既有聊天、记忆和界面能力。
  同步本轮后端对结构化模型输出、外部页面资料来源及重试一致性的修复。

代码、权重的许可证及下载来源见 [免费本地语音](LOCAL_SPEECH_INPUT.md)。
语音启动对照、20 段公开真人录音及噪声样例结果见 [语音测试记录](LOCAL_SPEECH_STARTUP_TESTING.md)。
这些小样本结果不是普遍中文准确率；实际麦克风、口音和环境噪声仍会影响效果。

## Android 更新

本轮将已实现的 droid-mcp 手机操作、情绪联动、环境光/接近传感器、可调冷却、回复触感、
通知预览、悬浮小窗和点开读屏同步到 GitHub。各入口继续遵守系统权限与用户选择的范围。
2026-10-20 补充 ARM64 Release APK `XinYu-Android-0.2.31-Preview.apk`，同时包含免费本地语音输入。
这些手机联动功能仅用于 Android。签名、升级、原生依赖与最终 APK 运行结果见
[Android 0.2.31 交付记录](ANDROID_0231_DELIVERY.md)。
Android 的逐项能力和测试边界见 [手机能力](ANDROID_PHONE_CAPABILITIES.md)、
[手机陪伴](PHONE_COMPANIONSHIP.md)、[悬浮陪聊](ANDROID_FLOATING_CHAT.md)。

「开口练习」已撤回，代码和入口不在本次版本中。「陪伴通话」仅为讨论中的方案，未实现。

## 安装与升级

下载 `XinYu-Windows-0.2.31.zip`，完整解压后运行 `XinYu/xinyu_flutter.exe`。
这是 Windows x64 免安装完整包，包含 Python 引擎、语音运行库和必要依赖；无需另装 Python。
语音模型按需单独下载，未把约 190 MiB 权重放入 ZIP。

先正常退出旧心隅，将新包解压到新目录，之后将快捷方式指向新目录中的 EXE。
聊天与记忆继续使用 `%LOCALAPPDATA%\XinYu\data`，升级不移动或删除该目录。
不要仅覆盖单个 EXE；需要保留完整引擎、DLL 与 `data` 文件夹。
可先通过应用内备份保留需要的数据，不为升级卸载或清空旧数据。

## 发布验证

发布前本地检查与构建记录保存在 `E:/XinYu-Dev/project-tests/windows-0231-20261019/`。
测试均使用自有合成数据或公开语音，没有读取日常聊天数据库或调用在线聊天模型。

- Ruff、格式检查及 mypy（173 个源文件）通过。
- Flutter analyze 与全量 214 项测试通过；Windows Release 界面重新构建。
- Python 全量 **2015 项通过、1 项跳过**；有一条已有 Starlette/httpx 弃用警告，无测试失败。
- 随包冻结引擎的两项真实进程测试通过，运行编号 `native-bundle-75c60430a98842c692fadbc9dc64ba8a`。
- 完整解压发布 ZIP 后，在独立合成目录启动实际 Windows 程序，确认 Flutter 窗口、随包引擎、
  回环监听和新数据库创建；程序收到关闭请求后正常退出，测试子进程全部结束。
  此项是启动/退出检查，不等于实际麦克风或所有界面交互验收。隐藏测试窗口首轮被可见窗口检查误报，
  改为核对自有进程的 Flutter 窗口类后通过；首轮结果保留在本地证据中。
- 使用发布包内实际 `sherpa-onnx-c-api.dll` 与 `onnxruntime.dll`，通过原应用识别器运行
  20 段真人录音、8 段模拟噪声/低音量及 1 段静音，29 段全部完成，转写与此前验收逐段一致。
  两个 DLL 与固定的 1.12.14 依赖逐字节相同；音频输入来自公开 WAV，不是现场麦克风录音。
- 随包 Python 源码、Flutter 构建输入与待发布源码逐项匹配；ZIP CRC 和解压后逐文件 SHA 校验通过。
- 真实应用进程运行编号 `4d949b71-99b5-4d5a-a237-1523030e7c98`：后端通过，离线模型的语言质量
  保持 `blocked`，预期退出码 2，不将其当作真实模型质量验收。
- 复用的 68 个 droid-mcp 上游文件 SHA-256 与固定修订一致；上传范围检查不含测试日志、
  录音、模型权重、聊天数据库或凭证文件。

## 附件

Release 原有 Windows ZIP、`INSTALL.md`、`SHA256SUMS.txt` 和 `delivery.json` 保持不变。
Android 附件为 `XinYu-Android-0.2.31-Preview.apk`、`ANDROID_INSTALL.md`、
`ANDROID_SHA256SUMS.txt` 与 `android-delivery.json`，两个平台分别记录验证范围和构建来源。
Windows 来自 `15ff7af2ea8565e0291b6152fb79cd8a51feba55`；
Android 来自补充原生库对齐修复的 `f77ee0880afcce88572db927cbfdf0a81b20e950`。
已发布标签保持原指向，Android 的准确源码提交可从其交付清单定位。
交付清单记录源码提交、文件大小、SHA-256 和验证范围，不上传测试对话与构建机私有数据。
安装包构建仍为手动流程，普通源码推送只运行 CI。

`XinYu-Windows-0.2.31.zip` 大小 **76,086,247 字节**，SHA-256：

```text
b43cad4336256be5b8cfb725b3455b001c2635d6759f89b3c1d2838324f75833
```
