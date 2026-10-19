# 陪我看消息

2026-10-19 加入源码。适用于 Android 9 及以上，尚未打包进交付 APK。

用户遇到难以判断语气、拿不定主意怎么回复的消息时，可以说：
「帮我看看小雨刚才的微信，不知道怎么回」。心隅发起一次读取确认，卡片写明应用、
标题筛选和条数；确认成功后，在原对话里继续理解消息、起草回复。
理解和措辞仍由当前聊天模型完成，MCP 提供此前缺少的手机通知预览。

## 使用

1. 在「连接的应用 → 手机能力」连接手机。
2. 将「陪我看消息」从关闭改为「每次读取前确认」。新连接与旧连接升级均默认关闭。
3. 在「手机权限与使用说明」单独授权「心隅 · 陪我看消息」的通知使用权。
   网易云播放控制的原有通知权限不能代替这项授权。
4. 回到心隅聊天，说明要一起查看微信或 QQ 的消息，确认读取卡片。

每次读取默认最新 1 条，最多 3 条。可按通知标题筛选用户指定的人或群；无匹配时不会
扩大到其他人。只读取当前通知栏中仍存在的预览，不能恢复已清除消息或读取完整聊天历史。
若应用只展示「收到一条消息」之类的占位文字，心隅也只能看到该文字，不会绕过隐藏设置。
通知可能缺少上下文，提示模型区分原文和推测，不断言对方的真实情绪、意图。

读取到的内容进入当前对话的工具记录，并发送给用户配置的模型，沿用现有 SQLite
保存与删除机制。此入口不发送消息、不触发通知按钮、不标记已读、不清除通知。
系统监听服务不实现通知到达时的收集，不建立通知缓存，不开启后台轮询。

## 复用与边界

- 新工具名 `read_chat_notifications`，复用固定版本 droid-mcp 的 `McpTool`、
  `ToolRegistry`、Schema 生成和 `InProcessTransport`，继续经过 Python ToolHub 的
  配置、确认、指纹检查、去重和恢复对话链路。无新增网络服务、账号或依赖。
- 上游源码和 SHA-256 清单保持不变。新增适配位于 `android/phone_bridge`。
  上游 `get_active_notifications` 只能读宿主自己的通知；`list_repliable_notifications`
  依赖后台通知缓存且只列带 RemoteInput 回复按钮的通知，因此未直接拿它读取微信预览。
  参考 [droid-mcp 固定版本](https://github.com/stixez/droid-mcp/tree/38723823a05852d3b2a655f48d817fc4bd3b406c)。
- `CompanionNotificationListener` 与原 `MusicNotificationListener` 独立。
  仅在收到系统连接回调且权限有效时调用快照接口；断开或销毁即释放服务引用。
  对应 [Android NotificationListenerService](https://developer.android.com/reference/android/service/notification/NotificationListenerService#getActiveNotifications())。
- 必须心隅在前台、屏幕亮且解锁；读取前后复核前台与权限。
  Android 边界和 Python Schema 都限定微信/QQ、条数及标题筛选长度。
  只投影当前用户的匹配通知，排除群组汇总、持续服务、来电、播放及推广类别。
  标题最多 120 字符，正文最多 800 字符，截断明确标记。
- 工具权限仅关闭/逐次确认，导入的 allow 也按 ask 执行。确认后继续原请求，重试不会
  再读更新的消息；对话有新指示、配置改变或权限撤销时停止。新请求须重新确认。
- 定时任务 API、模型创建任务入口及旧任务调度均拒绝此工具。手机主动陪伴授权不会
  自动开放此功能。通知结果标记为外部不可信数据，不能作为新的工具操作指令。
- 当前源码 Android 11+ 共 31 个手机工具；Android 9/10 共 30 个，后者不含滑动手势。

## 本地测试证据

产物目录 `E:/XinYu-Dev/project-tests/chat-notifications-20261019`，全部使用合成通知、
合成聊天和离线/脚本模型；没有连接真实微信、QQ 账号或个人消息。

- 最终 Python 全套 1,996 项通过、1 项跳过、0 失败，耗时 347.99 秒，
  证据 `full.xml`、`full.log`。
- 专项 Python 38 项通过，覆盖真实 HTTP 聊天、确认后恢复、拒绝、重试去重、新指示
  撤销旧确认、规则变更、升级默认关闭、参数边界、系统失败及定时入口；包含原有手机
  适配回归和模型上下文预算回归。证据 `focused-2.xml`。
- Android 实际 SDK 注册/执行通道的 Robolectric 测试共 21 项通过，其中新增 7 项。
  覆盖无 RemoteInput 的普通消息、指定应用/标题、最新排序、截断、空正文、清除后无缓存、
  用户配置文件隔离、权限独立、断连、销毁、后台和锁屏。证据 `native-2.log` 与
  `native/phone_bridge/build/test-results/testDebugUnitTest`。
- Flutter 新功能专项 7 项通过，覆盖默认关闭、导入权限、准确确认文案、独立授权通道，
  320/768/1024/1440 宽度、Tab/Enter/Escape 键盘和读屏 tooltip。证据 `flutter-focused-3.log`。
- Flutter analyze 与最终全套 178 项通过，证据 `flutter-analyze-final.log`、`flutter-final.log`。
  实际测试的 Flutter 副本为 `E:/XinYu-Dev/builds/8d989779dd734ced8530bf8cec633bf4/client`。
- Ruff 与 mypy 通过；后者检查 172 个源码文件。
- 隔离真实进程批次 `28548e98-0363-457e-be91-179c1e99f28f`：backend passed，
  language_quality blocked，退出码 2 为预期的离线质量评审状态，真实模型调用为 0，
  进程已关闭。运行时源码指纹 `1c3a42b1cf1a4c4fa8e1dfb8d99ed5fca2c8c88f0d59e18af961a964a3cb83b8`。
- `evidence-summary.json` 核对 104 个 Flutter 源码/测试文件和 77 个原生 Kotlin 文件
  与对应测试副本字节一致，原有 0.2.30 APK 哈希未变，本轮目录没有生成 APK。

首次测试发现的合成 Android 通知构造参数和定时测试环境开关问题已修正；读屏验证改为
检查 Flutter 实际输出的 tooltip 语义字段。失败日志 `focused.log`、`native-1.log`、
`flutter-focused-2.log` 保留，未删改失败结果。

尚未验证真实微信/QQ各版本的通知格式、不同厂商的通知权限行为，也未评审真实模型的
理解与回复质量。Robolectric 和脚本模型通过不代表以上两项通过。没有生成新 APK。
