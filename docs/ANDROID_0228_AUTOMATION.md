# Android 0.2.28：手机手势与真实网易云测试

2026-10-18 至 19 完成本机自动化。最终 APK 为 `0.2.28+31`，测试包名
`com.xinyu.xinyu_flutter.preview`，ARM64，SHA-256：
`345aab503a82d9593fe8f8e9d8ca3acc0711e712e539c9b73e8e0e8fda394a75`。

## 新增功能

- 复用 droid-mcp 的 `long_click_node`，按控件文字或 ID 长按，打开长按菜单。
- 复用 `gesture`，按刚读取的界面坐标滑动列表或应用控件，限制为 2–16 个点、10–3000 毫秒。
- 滑动要求 Android 11 以上，并利用系统 Insets 排除状态栏、导航栏、边缘系统手势区域。
  Android 9–10 仍可使用长按和原有控件滚动，共 25 项工具；Android 11 以上为 26 项。
- 延续 ToolHub 的确认、撤销、目标应用检查、写后重新读取及去重。旧连接的新界面工具保持关闭。
  在「连接 → 手机能力 → 界面操作」中开启，并授予系统无障碍权限。

## 最终通过的测试

| 范围 | 结果 | 证据 |
| --- | --- | --- |
| 原始最终 APK、Android 15 模拟器 | 38 项通过 | `android-local-9b2697f519524223b73cc045c9699c73` |
| 真实网易云曲库与客户端控制 | 9 项通过 | `android-local-668ff1d1dc0f40b69ee6d18def7d2815/music-mcp-1792339354004041000.json` |
| Python 全套 | 1,900 通过、1 跳过 | `.agent-tests/pytest-0228.log` |
| Flutter | 初次完整 157 通过；新增升级权限检查后手机专项 8 通过，analyze 通过 | `.agent-tests/build-0228-final.log` |
| Android 原生单元检查 | 7 通过 | `.agent-tests/android-0228-delivery/native-phone-tests.xml` |
| Ruff / mypy | 通过；mypy 169 个源文件 | 本机命令输出 |
| APK 内容与签名 | 212 个 Python 文件、169 个客户端输入、80 个 ARM64 ELF 校验通过；签名及 16KB 对齐通过 | `dist/android-0.2.28-preview/delivery.json` |

38 项覆盖真实 Flutter 连接页面、授权往返、应用冷启动与重启、嵌入引擎、原生依赖、
手机状态、音量确认/去重/撤销、亮度和勿扰读回、读取/点击/输入/密码遮罩，以及新增的
长按结果读回、实际列表滑动、系统栏坐标拒绝和错误目标应用拒绝。

音乐使用官网提供的 **8.6.76 兼容版、游客模式、Android 11**。搜索选择
《茉莉花(江苏民歌)》（中央民族乐团，ID 5266664），核对播放状态及进度递增；
暂停、继续、下一首、上一首、跳转 60 秒均有实际读回。最终自动化下一首是
《罗生门（Follow）》，先前探索轮还播放了《海屿你》。另核对网易云 UID 对应的
`AudioTrack` 为 `state:started`、`USAGE_MEDIA`，未把发送请求或元数据切换当作实际播放。
测试最后暂停播放，两个受控模拟器均已关闭。没有登录真实账号、模型调用、付费或发送行为。

## 验证边界

音乐测试的实际路径为：**主机运行项目原有 AndroidMusicClient/MCP 协议 → 测试传输 →
已安装最终 APK 的 MusicBridge → 网易云客户端与 Android MediaSession**。
歌曲 URI 通过 ADB 交给网易云；该测试不把此步骤算作 MusicBridge 前台启动验证。
`probe_android_music.py` 每次记录设备内 APK 的 SHA-256，最终 9 项均对应上述交付 APK。
这是实际服务集成测试，没有伪造曲库、播放器或播放结果，但不等于同一模拟器上的
Flutter → Chaquopy → MCP → 网易云完整界面联动通过，也不验证扬声器听感或真实模型选歌。

当前官方模拟器的限制：

- 网易云官网最新版 **9.6.08** 在 Android 15 ARM64 转译层启动时于 `libpoison.so` 崩溃；
  Android 11 的 32 位路径则出现网易初始化库 JNI 加载错误。
- 当前心隅 ARM64 Flutter/Python 运行时在 Android 11 的旧转译层触发 SIGILL。
- Android 13 Google APIs r17 官方 x86_64 镜像未提供 ARM 转译。

因此，最新版网易云及真机上的完整手机端联动仍待真机验证。没有修改、解壳或绕过网易云客户端。
原始 0.2.27 APK 的 Python/MCP 实际公开搜索此前已在 Android 15 通过；该音乐适配代码与本版一致。

## 失败与修复记录

- `android-local-a4c7c9e226504e2090eeab915203df38`：最新版网易云启动崩溃；公开 MCP 搜索通过。
- `android-local-02774dfb67f34d9a9718c341b42166e2`：Android 11 转译不支持当前心隅运行时；官方兼容版网易云可进入界面。
- `android-local-836c3981879c4048b627fa49795fa013`：Android 13 镜像缺少 ARM ABI，启动门槛检查拒绝继续。
- `android-local-c7b65619ff024322a9d5e5790a8b3906`：探针误用 `matches` 字段；改为 SDK 实际返回的 `nodes`。
- `android-local-2a8b09a1a0e442b98035f502f81bcb35`：长按和滑动读回通过，但状态栏坐标未被拒绝；生产代码补充 Insets 限制后最终批次通过。
- 网易云动画页面可能使 UIAutomator 无法取得新树。驱动改用每次唯一的设备 XML 路径并检查成功标记，禁止读取之前的树；实际音乐结果以原生状态、音频轨道和截图为证据。
- 中途新 Robolectric SDK 下载停滞，停止了该构建；目录数量的重复单元检查移除，最终目录及 Insets 由 Android 15 的实际探针覆盖，保留原有 SDK 环境的 7 项原生检查。

失败证据保留在 `.agent-tests`；原始截图、日志和测试数据不提交到 Git。

## 复现入口

`tool/smoke_android_local.py` 创建全新受控模拟器，接收 SDK、ADB、APK 和探针 APK 路径；
`tool/build_android_probe.py` 构建独立测试 APK，不向产品 APK 添加测试入口。
`tool/smoke_netease_android.py --adb <adb.exe> --run-id <仍运行的受控批次>`
执行 9 项音乐集成检查，前提为兼容版网易云已完成游客初始化并授予心隅通知使用权。
`tool/probe_android_music.py` 仅允许仍在运行且 AVD 名称匹配的受控模拟器。

安装包来源：[网易云官方下载页](https://music.163.com/st/download)。最新版来自该页的
`/api/android/download/latest2`，兼容版来自同页 Android 5.x 链接。
两份 APK 签名证书 SHA-256 相同：
`54254d2be09daef48dedc2b4a4f497d153e14ed9d70814fc9c360ee9240827f7`。
兼容版 APK SHA-256 为 `60121058aab6730a05e15c65fb924548f8d4be7f607b132285748e9c723b54f3`；
最新版为 `4c2e8791c6d00b952332eb698837bbea72bb4384518b75fe895bd4fdccb572d3`。
