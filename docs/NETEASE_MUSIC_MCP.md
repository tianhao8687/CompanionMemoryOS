# 网易云音乐连接

## 当前交付：0.2.17 / build 20

`dist/music-player-20261015-v6/` 将明确的陪听分享接入现有共同经历记忆。
歌词点歌能力保留，新增歌曲与用户原话的来源关联、同歌指代召回及更正/遗忘验证。
详见 [陪听记忆接入](LISTENING_MEMORY.md)。

## 之前交付：0.2.16 / build 19

`dist/music-player-20261015-v5/` 增加歌词点歌：在普通聊天或「一起听」中说
「帮我找并播放包含这句歌词的歌：……」。现有 DeepSeek 工具循环调用歌词搜索，
依据实际返回的片段匹配核对歌曲。明确匹配、版本无歧义且权限允许时交给网易云；
不同歌手、现场版等存在歧义时展示最多三个歌曲卡片供用户选择。

卡片显示歌曲、歌手、专辑、封面及操作回执，支持直接播放和进入「一起听」。
点选卡片只授权本次选中的歌曲，不修改后续 AI 操作权限。仅分享歌词不应触发点歌；
没有歌词匹配证据的候选不能由 AI 在本轮自动播放，用户仍可明确点选候选。
打开请求和已确认播放分别显示，播放权限继续由网易云客户端处理。

Windows 和 Android 共用搜索与卡片逻辑，播放器交接仍走各自本机桥接。
已连接的内置网易云工具会刷新歌词搜索参数并保留现有权限。没有加入音频模型、
歌曲音频采集或上传。规则已接入，真实模型选歌表现与安卓手机实测尚未验收。
实现、验证和限制见 [歌词点歌验收记录](LYRIC_SONG_REQUESTS.md)。

## 之前交付：0.2.14 / build 17

`dist/music-player-20261015-v3/` 为本次更新，增加第六个 MCP 工具 `netease_seek`。
Windows 对话改为右侧独立区域，手机为可随键盘收缩的播放器和对话区；歌词支持真实时间线
自动跟随，或用户明确手动对齐；选择歌词可填入输入框后发送。真实音频输入尚未实现。
详见 [布局、同步与音频接入规划](MUSIC_LISTENING_REDESIGN.md)。

本机 Windows 网易云报告 `seek=false`、时间线为零，因此无法通过当前系统接口拖动歌曲。
支持 `seek` 与有效时长的设备可拖动；Android 桥接检查 `ACTION_SEEK_TO` 并回读位置确认。
手机媒体能力待真机测试，不以 APK 编译成功代替实测。

验证：Python 1,562 通过 / 1 跳过，Ruff 和 Mypy（149 文件）通过；Flutter analyze 与
全量 121 项通过，随后新增实际歌词滚动用例及截图专项 6 项通过。
冻结引擎隔离测试 `native-bundle-9c74054b2bde417d9d718dc06edcb774` 通过；
真实应用进程 `9e9300cf-23bb-4132-b08c-ac02557bf5b5` 后端通过，语言评审未执行（无真实模型批次授权）。
Windows 压缩包 956 文件与展开目录逐一一致，冻结 MCP 实际发现 6 个工具，未执行播放操作。
APK 签名、16 KB 对齐与原生桥接检查通过；沿用此前测试版签名与包名，版本号提高到 17。

2026-10-15。Windows 本机接入已实测，Android 本机适配已实现，手机联调待安装包测试。
在聊天里提出明确的音乐请求，伴侣通过现有 MCP 权限与操作账本执行，回复继续留在原对话。
连接本身不登录账号；歌曲实际播放、会员和版权权限均由网易云官方客户端处理。

## 使用

1. 在 Windows 安装并打开网易云音乐。播放控制需要在网易云设置中开启系统媒体控制
   （SMTC），如客户端提示则重启，再播放一首歌以建立媒体会话。
2. 在心隅「设置 → 连接」连接网易云，并开启「使用连接的应用」。连接会启动本机 MCP 服务并
   发现工具，不自动播放歌曲。网页入口为「能力与定时 → 工具连接 → 填入网易云模板」，
   勾选启用、保存后点击「连接并发现工具」。
3. 每个工具默认「每次确认」。聊天出现待确认提示时，打开面板核对具体参数，选择
   「确认并继续」或「拒绝」。也可分别设置允许自动调用或禁用。
4. 可说「帮我在网易云找陈奕迅的孤勇者」「用网易云打开这首歌」「暂停网易云」
   「看看网易云现在放的什么」「网易云换下一首」。存在原唱、翻唱、现场版等候选时先选版本。

需要配置支持工具调用的聊天模型。离线演示不替代真实模型的工具选择验收。
如果已关闭全局工具循环，连接仍可保存，但聊天不会调用工具。
Android 在同一个入口连接手机上的网易云；再进入「一起听」，按需开启系统通知使用权。
手机上先播放一首歌，再回到心隅检查歌曲与播放状态。

## 工具

| 工具 | 作用与返回边界 |
| --- | --- |
| `netease_status` | 检查客户端安装及系统媒体会话；不启动网易云 |
| `netease_search_songs` | `search_type=song` 搜歌名/歌手，`lyrics` 搜用户给出的歌词；最多 10 首，返回歌曲 ID、歌手、专辑、可用封面和片段匹配证据 |
| `netease_open_song` | 将歌曲 ID 交给客户端；`delivery=requested`、`playback_verified=false` 仅表示提交打开请求 |
| `netease_playback_state` | 读取网易云会话的歌曲、歌手、播放状态及可用控制；提供时也返回实际播放位置、时长、采样时间和速度 |
| `netease_control` | `play`、`pause`、`next`、`previous`；操作后核对状态，无法确认时返回 `uncertain` |
| `netease_seek` | 设备开放跳转能力时改变播放位置，并回读确认；未开放时明确返回不可用 |

工具只接收完成操作所需的关键词、歌曲 ID 或控制动作。搜索词会发送给网易云；结果和
当前播放信息会进入本机操作记录及本轮模型上下文。没有读取账号 Cookie、听歌历史、
私人歌单、下载音频或创建另一套音乐偏好库。

## 接入方式

源码环境安装项目依赖后，可独立作为标准 stdio MCP 使用：

```powershell
.\.venv\Scripts\python.exe -m companion_agent.integrations.netease
```

非标准安装目录可增加 `--executable "D:/Apps/CloudMusic/cloudmusic.exe"`，必须是已存在的
绝对路径。通常由注册表卸载条目或标准目录发现，不需要手工配置。模型不能传入程序路径。

心隅内置模板自动选择源代码入口或冻结包的 `xinyu-engine.exe --mcp-server netease`。
冻结入口在打开应用数据库前分发，不另开心隅或共用聊天库。Windows 打包收集 WinRT
投影及原生扩展，终端用户无需安装 Python。

通过 HTTPS 向固定网易云搜索端点请求公开元数据，限制关键词长度、数量、时间、响应大小，
拒绝重定向；接口格式变化或网络失败会明确报错。该端点及 `orpheus` 协议属于客户端兼容
接入方式，未依赖一份有稳定性承诺的网易云开放平台 API。

歌曲交接使用验证过的 `cloudmusic.exe` 与单独的 `--webcmd=orpheus://...` 参数；不运行
Shell、不改协议注册表。本机网易云 3.1.38.205386 的协议注册命令确认使用 `--webcmd`。
仅找到程序不能证明客户端已接受具体歌曲，更不能证明已开始播放。

状态与控制优先使用 Windows GSMTC，只匹配 `SourceAppUserModelId=cloudmusic.exe`（忽略大小写）。
系统未提供播放位置时，已验证客户端可补充读取本地播放时钟和歌曲 ID，详见
[自动同步适配与限制](NETEASE_AUTO_SYNC.md)。这一补充不提供播放写入能力。
没有会话、多个匹配会话或客户端未提供该操作时拒绝控制，不向当前默认播放器发送全局媒体键。
接受请求但未观察到状态变化时保留 `uncertain`，不自动重试；下一首遇到同名曲目也可能需要
人工核对。SMTC 没有可靠的网易云歌曲 ID，因此不能用同名标题证明打开了某个精确 ID。

原生 Windows 仅开放交互式 MCP，后台定时任务与消息渠道继续禁用。
Android 使用内置 JSON-RPC MCP peer，只接收网易云这一个 native 连接；不依赖 WinRT、
桌面 MCP SDK、子进程或任意远端 MCP 服务。两端分别控制当前设备上的网易云。

## Android 与一起听（2026-10-15）

Android 桥接 `MediaSessionManager`，要求用户主动在系统中开启心隅的通知使用权。
监听服务不实现通知内容处理，只枚举媒体会话并精确匹配 `com.netease.cloudmusic`。
没有权限、无会话、多个匹配会话、播放器不提供对应动作时拒绝；未确认的控制结果保持
`uncertain`，不重试。打开歌曲采用限定网易云包名的 Intent，仅在心隅前台调用；
客户端接受跳转只代表 requested，不证明精确歌曲已经播放。

内置 peer 完成 initialize、initialized、tools/list、tools/call，沿用现有工具发现、
schema 指纹、参数白名单、确认队列和幂等记录。播放按钮由用户本次点击确认对应操作，
不会因此把 AI 权限改成自动允许。默认 AI 每次操作都需确认。

一起听的临时状态只在内存中保存，消息写入原会话，继承授权、证据限制和删除链路。
界面及主动发言边界见 [UI 标准](UI_STANDARD.md)。AI 获得的是歌曲元数据，不是音频或歌词。

播放页通过授权的 `POST /api/music/lyrics` 请求显示用歌词，必须携带当前会话、活动及歌曲
标识。歌曲匹配仍经过现有 MCP 搜索权限、参数白名单和接口校验。歌词与封面详情来自固定
网易云 HTTPS 端点，限制响应大小、超时和重定向，封面仅允许网易云图片 CDN。
歌词缓存只在进程内短期保留，不自动进入模型上下文或会话数据库，也不会创建音乐偏好。
这不是新增模型工具，原有五个 MCP 工具保持不变。

匹配需要完整歌名（保留 Live / 翻唱等版本）、歌手集合及专辑唯一对应，有媒体时长时再校验
时长；无法唯一核对时让用户选版本。LRC 支持多时间标签、毫秒、全局 offset、纯音乐与无时间
标签文本。异步返回前重新检查活动、歌曲、权限，切歌或离开不会显示过期结果。
接口属于客户端兼容接入，网易云调整接口后可能需要更新适配。

时间线参考 [Windows 时间线属性](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessiontimelineproperties?view=winrt-26100)
和 [Android PlaybackState](https://developer.android.com/reference/android/media/session/PlaybackState)。
歌词接口结构参考[公开兼容实现](https://github.com/NeteaseCloudMusicApiEnhanced/api-enhanced/blob/master/module/lyric.js)，
并已对网易云自身域名做只读连通性检查；不经过第三方歌词代理。
本机 Windows 网易云此次提供歌曲和播放状态，但时间线为空，故该客户端显示可手动浏览的歌词。

参考：[Android 媒体会话](https://developer.android.com/reference/android/media/session/MediaSessionManager)、
[通知使用权服务](https://developer.android.com/reference/android/service/notification/NotificationListenerService)、
[MCP 生命周期](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)。

这批本机打包复用了项目 xinyu-v0.2.11 已发布 APK 内相同版本的四个 Android 原生依赖，
逐字节保留其 ARM64 二进制及 CPython 3.13 字节码；先核对发布包 SHA-256，再检查 ELF
架构和 16 KB 对齐。来源报告保存在构建缓存的 `recovery-provenance.json`。
这是已发布依赖的恢复复用，不是本机重新编译这些第三方原生库。
当前引擎、Flutter 界面和 Kotlin 音乐桥接均重新打包。

## 调研依据

- [Windows GSMTC 会话 API](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession?view=winrt-26100)：定向媒体会话与动作返回值。
- [Microsoft 的会话枚举示例](https://devblogs.microsoft.com/oldnewthing/20231108-00/?p=108980)：按来源识别会话。
- [PyWinRT 类型与包说明](https://pywinrt.readthedocs.io/en/stable/types.html)：Windows Python 投影。
- [社区客户端 MCP 实现](https://github.com/Seraph310/cloudmusic-desktop-mcp/blob/a61a611bf1284d9663df2742ec83f8769403465d/server.py)：搜索端点和歌曲协议格式参考。本实现独立编写，未采用其全局媒体键和内部调试端口控制。
- [SMTCPlayer 项目说明](https://splay.asia/)：网易云需开启 SMTC 的客户端前置条件。

## Windows 首阶段验证记录

自动测试采用合成媒体会话与 HTTP 响应，覆盖错误播放器隔离、多个会话拒绝、参数校验、
请求失败、不确定结果不重试、权限确认与续跑。测试不控制真实音乐客户端。
真实 stdio 握手已发现全部五个工具，公开搜索已返回歌曲及版本；已探测本机客户端安装。
用户开启 SMTC 后，已在网易云 3.1.38.205386 上实际核对继续、暂停、下一首、上一首，
并观察到歌曲交接后对应歌名、歌手与 playing 状态；测试结束回到原歌名与暂停状态。
SMTC 无歌曲 ID，因此这不是精确 ID 或完整音频内容的验证。

本地验收：

- Python 全量：1,522 passed、1 skipped；最终音乐与原生权限回归 42 passed。
- Ruff 全项目通过；Mypy 145 个源码文件通过。
- Flutter analyze 与全量 110 项测试通过，覆盖连接、权限、确认、启动、
  320 / 768 / 1024 / 1440 宽度和 Android 不支持提示；Windows release 编译通过。
  全量首轮发现本机仓库未就绪会使可选工具连接阻断初始化，已修复并回归。
- 冻结引擎已实际 stdio 发现五个工具、读取网易云媒体状态，证明打包后的 WinRT 可加载。
- 冻结引擎隔离验收通过：`native-bundle-6a89785006e248e6b2a5810889517a07`。
- Edge 真实网页冒烟通过：`a72183b7-2ce2-4d71-9203-c2a727158d76`。
- 真实应用离线场景：`6962dde7-6222-4ba1-b08e-84d99cfb00ab`，后端 passed；语言质量
  blocked，原因是未运行授权的真实模型评审。未把离线结果算作自然语言或模型选歌验收。

没有调用付费模型、上传 GitHub 或替换已安装的应用。原始合成证据留在忽略的 `.agent-tests/`。
