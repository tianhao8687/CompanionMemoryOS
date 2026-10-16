# Windows 点歌失败：MCP 子进程生命周期根因

2026-10-16，在实际运行的 0.2.22 上定位。下文保留原始根因证据；
0.2.23 已完成业务修复、打包程序静默冷启动与最终引擎复用验证，见文末及 [修复验收](MUSIC_0223_WINDOWS.md)。

## 结论

`netease_windows.open_song/open_app` 在临时 MCP 服务内通过 `subprocess.Popen` 启动
`cloudmusic.exe`，创建成功后立即返回。`MCPClient` 每次调用使用独立 stdio 会话，得到结果
就关闭会话。已安装 MCP SDK 为 Windows 服务进程配置 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`，
新建的网易云传令进程也属于该 Job；关闭最后一个 Job 句柄会结束这些子进程。

因此“创建进程成功”并不代表歌曲指令完成交接。传令进程可能在交接前就被清理，网易云仍是旧歌。
0.2.22 的延迟状态核对、前后读取隔离和卡片刷新无法挽救已经被结束的传令进程。

实现位置：

- `companion_agent/integrations/netease_windows.py`：`open_song`、`open_app`。
- `companion_agent/automation/mcp_client.py`：每次调用独立进入并退出 `stdio_client`。
- 本机 SDK `mcp/client/stdio/__init__.py`：创建 Windows Job 管理的服务进程。
- 本机 SDK `mcp/os/win32/utilities.py`：Job 使用 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`。

官方机制：[Microsoft — Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。
普通 `CreateProcess` 子进程默认继承父进程的 Job；带此限制的最后一个 Job 句柄关闭时，
其中仍存活的进程会被终止。

## 实测证据

未读取日常聊天数据库，未调用模型，未重启网易云。真实播放测试使用用户已经点选的歌曲。

| 路径 | 结果 | 本地证据 |
| --- | --- | --- |
| 实际 0.2.22 冻结引擎，正常短 MCP 调用《鲜花》2086327879 | 工具返回 succeeded；约 7 秒后仍是暂停的 Johnny Boy | `.agent-tests/0223-packaged-handoff.json` |
| 开发环境，保留同样短 MCP 调用链及相同歌曲 | 同样失败，排除仅冻结打包造成的差异 | `.agent-tests/0223-source-mcp-handoff.json` |
| 开发环境直接执行同一歌曲打开函数，调用者保持运行 | 第 1 秒旧歌；第 3 秒《鲜花》playing、正确 ID、非零进度；传令进程随后正常退出 | `.agent-tests/0223-direct-handoff.json` |
| 原 0.2.22 冻结引擎，通过 MCP 请求《泪海》，保留会话约 6 秒 | 从《鲜花》切到《泪海》，正确 ID 和前进的时间轴 | `.agent-tests/0223-held-session-handoff.json` |
| 实际 0.2.22 `netease_open_app`，检查 Windows Job 及子进程句柄 | 新 `cloudmusic.exe` PID 38096 在同一 Job，收尾前仍运行（259），会话关闭后已终止；全程约 1.227 秒 | `.agent-tests/0223-real-launcher-job-proof.json` |
| 无害合成子进程，计划 3 秒后写标记；使用相同 MCP SDK | 收尾前仍运行，约 1.114 秒已终止，标记未写入 | `.agent-tests/0223-job-lifetime-proof.json` |

末次请求《鲜花》时，测试开始前目标歌已在播放；`.agent-tests/0223-same-song-held-session.json`
只能证明状态读取，不能作为这次交接成功的证据，不用于根因推断。

原来的单元测试使用立即改变播放状态的合成播放器；之前的实机成功验证直接调用打开函数，
没有经过实际 MCP 会话关闭。这是此前漏检的原因。

## 正确修复边界与验收要求

把用户应用的启动生命周期与短 MCP 调用分离，例如由常驻主进程承担内置网易云启动交接。
不能仅增加读状态的等待时间，也不能全局取消第三方 MCP 服务的子进程清理。
所有原有权限、歌曲来源验证、动作记录和幂等规则应继续生效。

必须从实际交付包验证：已经运行时可以点歌；MCP 调用结束后交接仍能完成；冷启动时网易云
不会随工具收尾退出；退出心隅不会意外结束网易云。要同时覆盖普通应用启动和按歌曲启动。

## 0.2.23 修复

内置 Windows 网易云的 `netease_open_app` / `netease_open_song` 改由常驻主引擎执行。
仍使用原 FastMCP 定义和参数验证，核对完整工具指纹，保留 ToolHub 的权限、来源、动作记录和幂等。
第三方 MCP 服务继续使用原短会话及 Job 清理，没有放开通用进程逃逸。

另补充了冷启动后媒体会话尚未建立时的有限只读等待。每次仍只提交一次歌曲指令。
静默启动使用隐藏窗口和心隅自身短时焦点保护，最终实现中没有最小化操作。

0.2.23 静默启动实现的打包引擎冷启动验收：
`music-cold-0223-675c715ee28843e1baa7c409169d93df`。
从没有网易云进程/媒体会话开始，经实际 HTTP 选歌接口、ToolHub、MCPClient 打开《鲜花》；
约 3.674 秒返回 verified，准确 ID 2086327879、playing、进度持续增加。
心隅真实窗口前台 PID 29012 全程保持；启动保护结束后网易云可见窗口为空。
关闭发出指令的打包引擎后，网易云仍播放至 14.13 秒。

随后仅补充已运行客户端复用，最终引擎验收
`music-open-0223-e1a30590d3c646d59a94d28fc8f8f0a8`：打开请求没有激活原窗口，
歌曲、暂停状态和进度保持不变。两批使用的引擎指纹分别记录在修复验收文档。

本轮固定一首歌，没有再次切歌。早期最小化方案与受手动操作影响的失败结果保留在
`.agent-tests`，不作为最终版本的通过证据。没有读取日常聊天数据库或调用真实模型。
