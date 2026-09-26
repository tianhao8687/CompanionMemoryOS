# 心隅 · Windows / Android 本地客户端

Flutter 玻璃界面 + 原有 Python 记忆引擎。电脑和手机各自保存聊天与记忆，
不互通，不依赖电脑给手机提供服务，也不需要租服务器。当前源码和实际产物状态见
[本地版交付记录](../../docs/LOCAL_APP_DELIVERY.md)；源码接入不等于安装包已经验收。

旧 Android `0.2.0+2` APK 已确认存在启动缺陷，请使用
[启动修复记录](../../docs/ANDROID_STARTUP_REPAIR.md)列出的修正版本。

## 应用行为

- 正常入口自动启动本机引擎。启动失败会显示错误，不自动切到示例回复。
- Windows 启动安装目录中的 `engine/xinyu-engine.exe`，随机监听回环端口；
  主窗口退出会关闭引擎的输入管道。用户无需单独安装 Python。
- Android 通过 Chaquopy 在应用进程内启动相同引擎，使用应用私有目录。
  ARM64 APK 已通过完整编译、签名和 ZIP 对齐检查；设备运行需要单独验收。
- Windows 数据在当前账号的 `%LOCALAPPDATA%\XinYu\data`；Android 在应用私有
  `files/xinyu-data` 中。不会自动打开网页应用的 `.agent-data/romance`。
- 模型默认使用离线规则回复，**不是本地大模型**。联网聊天需在设置中选择 API 模式，
  填写自己的模型信息和 Key，并启用消息处理及本机保存授权。
- 发送前缺 Key 或未确认聊天选项时弹出原因说明，保留草稿，点击“去设置”才进入连接选项。
  其他已捕获的操作失败使用统一玻璃弹窗；后续功能通过控制器的 reportFailure/reportProblem 接入。
- Key 默认仅用于当前运行。可选择系统安全存储：Windows 凭据管理器、Android Keystore。
  Key 不写入 SQLite，也不包含在聊天备份中。
- 支持新会话、分页历史、流式回复、同请求重试、停止回复、自定义风格、记忆更正和遗忘。
- 设置分为“相处设定、外观、消息、连接与数据”。外观提供标准、大号、特大字号及预览，
  保存进当前设备的 SQLite 设置，重启和备份恢复后保留。玻璃质感统一设计，不提供强度滑块。
- 备份导出完整 SQLite 快照；恢复前验证并在下次引擎启动时应用，保留恢复前副本。
  备份上限 64 MB。备份包含私人内容，遗忘不会清除以前导出的副本。
- 支持当前/全部聊天搜索、前后文查看，AI 内置表情包及用户导入图片/GIF。
- 顶部书本打开记忆手账：分类、重要标记、更正、遗忘和来源；可保存带照片的共同回忆，
  管理纪念日、约定与每年提醒。长按或右击消息可引用回复、保存回忆。
- 长按或右击消息也可复制、收藏、多选；多选支持批量复制/收藏，没有新增重发或重新生成。
  点角色名或双方头像进入独立角色主页，编辑资料与头像、打开收藏夹。
- 每个会话保存草稿和阅读位置；输入框上方常驻“回到底部”按钮，空白会话时置灰。
  轻微上翻也会保留阅读位置，新消息不抢位置；点击按钮回到最新消息。
  可开启自然聊天节奏：连续纯文字短暂停顿后合成一次回应，AI 原有段落显示为相邻气泡。
- Android 可以按用户授权在后台结合聊天和记忆主动联系，设置频率、免打扰和系统通知；
  需要在线模型及设备安全保存的 Key。Android 系统和厂商省电会影响调度，强行停止后需重新打开。
  本地应用不启动微信、设备/MCP 连接或具有外部执行权限的工具调度器。

新增功能见 [聊天操作、阅读位置与角色主页](../../docs/CHAT_EXPERIENCE_AND_PROFILES.md)、
[手账、日期与引用](../../docs/JOURNAL_AND_QUOTES.md)及
[搜索、表情包和主动消息](../../docs/CHAT_SEARCH_STICKERS_OUTREACH.md)，
本地 Android 0.2.6 圆润界面测试包见 [交付与检查记录](../../docs/ANDROID_026_DELIVERY.md)。

侧栏、消息气泡、输入框和弹窗保留背景模糊、半透明边框和玻璃层次。
选项、按钮与下拉选中项统一胶囊形或大圆角，窄屏设置入口按两列完整显示。
桌面与窄屏共享布局，演示模式仅用于开发与测试。

## 构建

使用 Flutter 3.47.5 / Dart 3.13.4，Python 3.12+ 的项目虚拟环境。
Windows 需要 Visual Studio C++ 桌面工作负载、CMake 和 Windows SDK，
Inno Setup 6，以及项目环境中的 `pyinstaller==6.22.3`。Android 需要 JDK 21、Android SDK 36、
Python 3.13 构建解释器和三个 Android ARM64 原生 wheel。

在仓库根目录运行：

```powershell
.\clients\xinyu_flutter\tool\build_local.ps1 -Target test -FlutterSdk <Flutter目录>
.\clients\xinyu_flutter\tool\build_local.ps1 -Target windows -FlutterSdk <Flutter目录>
.\clients\xinyu_flutter\tool\build_local.ps1 -Target android -FlutterSdk <Flutter目录> `
  -AndroidSdk <Android-SDK目录> -JavaDirectory <JDK目录> `
  -BuildPython <Python-3.13可执行文件> -AndroidWheels <Android-wheel目录>
```

脚本复制到新的英文构建路径，执行分析和 Flutter 测试，再生成应用；不镜像删除源码。
也可使用准备好的 [GitHub Actions 流程](../../.github/workflows/local-apps.yml)；
先完成本地检查和测试、展示结果，得到用户明确同意后再上传代码并手动运行。
代码推送不自动打包安装程序。
流程已经上传并运行，具体版本、下载地址与验证边界见交付记录。
Windows 产物包括 `XinYu-Windows-Setup.exe`（当前用户安装，无需管理员）和
`XinYu-Windows.zip`（免安装，必须完整解压）；Android 为 `XinYu-Android-arm64.apk`。
构建机输出位于 `dist/xinyu-local/<构建ID>/`。用户电脑交付目录见交付记录。
Android 构建当前使用开发签名，只用于本地验收。不同构建机的开发签名可能不同，
不保证覆盖安装；正式分发及持续升级前需配置并妥善保管固定签名密钥。
卸载安卓应用会清除其私有数据，请先使用导出备份功能。
旧的 `tool/build.ps1` 只保留测试与玻璃性能评估入口，不能生成缺少引擎的交付包。

### Android 原生依赖

`pydantic-core`、`rpds-py`、`tiktoken` 没有本次所需的现成目标 wheel；
保持原记忆引擎和准确 tokenizer，需要从上游源码交叉编译。
`cibuildwheel` 的 Android 构建支持 Linux / macOS，不支持直接在 Windows 构建。

在另一个具备 Python 3.12+、Java 21 和 Android SDK 的 Linux/macOS 构建环境中：

```sh
python -m pip install cibuildwheel==4.2.1
python clients/xinyu_flutter/tool/build_android_wheels.py --check
python clients/xinyu_flutter/tool/build_android_wheels.py --output /absolute/path/xinyu-wheels
```

这三个 wheel 已在 Actions Linux runner 从源码编译成功。
脚本下载明确版本的官方 PyPI 源码并核对 SHA-256，保存失败日志和构建清单，
检查 ARM64 ELF 和 16 KB 段对齐。它不宣称完成手机导入、FTS5、APK 对齐或实际运行验证。
将输出目录传给上面的 `-AndroidWheels` 后再构建 APK。
打包脚本还会下载并校验固定版本 SQLite 3.50.4 源码，由 Android NDK/CMake
构建启用 FTS5 的 `libsqlite3_python.so`。最终 APK 检查同时验证 FTS5 与 Python
反射调用的 Java 凭据类，防止依赖缺失或 R8 删除桥接组件后仍交付成功。
具体依赖钉在 `engine/requirements-android.txt`；引擎源码与 tokenizer 数据由
`tool/prepare_engine.py` 单独打入包，不随应用从网上下载。
前序探测证据见 [独立手机版路线验证](../../docs/ANDROID_ENGINE_FEASIBILITY.md)。

## 开发与验收

Flutter 测试使用合成数据与本地 HTTP 替身。实际进程测试规则见
[聊天验收说明](../../docs/CHAT_QUALITY_TESTING.md)。不要用日常数据库进行测试。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_local_runtime.py
.\.venv\Scripts\python.exe clients/xinyu_flutter/tool/smoke_native_engine.py `
  --engine <打包后的xinyu-engine.exe>
```

开发时可以设置 `XINYU_DEVELOPMENT_PYTHON` 指向项目虚拟环境 Python，
`XINYU_DATA_DIR` 指向新的合成数据目录，并从仓库根目录启动 Flutter Windows 程序。
编译时加 `--dart-define=XINYU_DEVELOPMENT=true` 才会显示开发服务/演示切换入口。

原型阶段的截图与性能记录保留在 [旧验证记录](../../docs/FLUTTER_PROTOTYPE_VALIDATION.md)，
它们不能用来证明当前本地软件已经通过 Windows/Android 验收。本次范围是 Windows 和 Android。
