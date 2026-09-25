# 心隅 · Windows / Android 本地客户端

Flutter 玻璃界面 + 原有 Python 记忆引擎。电脑和手机各自保存聊天与记忆，
不互通，不依赖电脑给手机提供服务，也不需要租服务器。当前源码和实际产物状态见
[本地版交付记录](../../docs/LOCAL_APP_DELIVERY.md)；源码接入不等于安装包已经验收。

## 应用行为

- 正常入口自动启动本机引擎。启动失败会显示错误，不自动切到示例回复。
- Windows 启动安装目录中的 `engine/xinyu-engine.exe`，随机监听回环端口；
  主窗口退出会关闭引擎的输入管道。用户无需单独安装 Python。
- Android 通过 Chaquopy 在应用进程内启动相同引擎，使用应用私有目录。
  Android 原生依赖还需要构建验证，当前不是已经交付的独立 APK。
- Windows 数据在当前账号的 `%LOCALAPPDATA%\XinYu\data`；Android 在应用私有
  `files/xinyu-data` 中。不会自动打开网页应用的 `.agent-data/romance`。
- 模型默认使用离线规则回复，**不是本地大模型**。联网聊天需在设置中选择 API 模式，
  填写自己的模型信息和 Key，并启用消息处理及本机保存授权。
- Key 默认仅用于当前运行。可选择系统安全存储：Windows 凭据管理器、Android Keystore。
  Key 不写入 SQLite，也不包含在聊天备份中。
- 支持新会话、分页历史、流式回复、同请求重试、停止回复、自定义风格、记忆更正和遗忘。
- 备份导出完整 SQLite 快照；恢复前验证并在下次引擎启动时应用，保留恢复前副本。
  备份上限 64 MB。备份包含私人内容，遗忘不会清除以前导出的副本。
- 本地应用当前不启动微信、设备/MCP 连接或后台定时服务。

侧栏、消息气泡、输入框和弹窗保留背景模糊、半透明边框和玻璃层次。
桌面与窄屏共享布局，演示模式仅用于开发与测试。

## 构建

使用 Flutter 3.47.5 / Dart 3.13.4，Python 3.12+ 的项目虚拟环境。
Windows 需要 Visual Studio C++ 桌面工作负载、CMake 和 Windows SDK，
以及项目环境中的 `pyinstaller==6.22.3`。Android 需要 JDK 21、Android SDK 36、
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
仅手动运行或推送到 `codex/local-apps-*` 专用构建分支时触发。
该流程目前仅保存在本地，未上传或运行。
Windows 产物为 `dist/xinyu-local/<构建ID>/XinYu-Windows.zip`，必须完整解压。
Android 构建当前使用开发签名，只用于本地验收；正式分发前配置并妥善保管长期签名密钥。
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

脚本下载明确版本的官方 PyPI 源码并核对 SHA-256，保存失败日志和构建清单，
检查 ARM64 ELF 和 16 KB 段对齐。它不宣称完成手机导入、FTS5、APK 对齐或实际运行验证。
将输出目录传给上面的 `-AndroidWheels` 后再构建 APK。
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
