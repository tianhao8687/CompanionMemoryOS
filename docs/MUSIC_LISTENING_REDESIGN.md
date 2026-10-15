# 一起听：对话、同步与真实音频边界

2026-10-15。本次目标是让音乐与陪伴对话同时可见，并明确播放器实际开放的能力。

## 界面

- Windows 宽窗口采用唱片 / 歌词 / 对话三栏，较窄窗口采用播放器 / 对话两栏。
  对话从右上方开始显示，包含用户与 AI 的来回；输入框在对话栏内，历史独立滚动。
- Android 采用较小唱片与歌词切换，下半部分保留对话区域。键盘出现时将播放器收成歌曲条，
  优先显示聊天和输入；大字体下减少装饰并保持输入与发送可见。
- 沿用 Noto Sans SC，正文 16 / 400，副文 12–14 / 400，歌曲标题 21–26 / 500，
  歌词 18 / 400、当前句 21 / 500。背景 #20282A，文字 #F6F2E9，辅助文字 #C8CFC8，
  控制强调 #EADCC3，分隔线 #FFFFFF / 15%。旋转唱片仍是唯一主要动效。
- 点击歌词可选择「聊聊这句」，先填入输入框，用户发送前不会调用模型。
  AI 能力说明集中在对话栏的信息按钮中，不用重复的免责声明挤占正常聊天。

## 歌词和播放进度

后续改进：0.2.15 对本机已验证的网易云 Windows 客户端增加自动读取位置，
手动对齐只在无法取得位置时作为备用。实现和版本限制见 [歌词自动同步](NETEASE_AUTO_SYNC.md)。

媒体时间线可用时自动逐行高亮、滚动。无时间线时，用户可以在听到某句时点击
「歌词从这句开始跟随」，建立仅在当前前台活动内有效的歌词时钟。
手动对齐不是实际播放位置；暂停状态同步后停止时钟，切歌、断开、离开前台会失效。
在外部播放器跳转但没有时间线上报时，需再次对齐，界面明确标示该状态。

新增 `netease_seek` MCP 工具，沿用已有发现、权限、操作去重和确认链路。
UI 仅在播放器报告 seek 能力且给出有效时长时开放拖动；松手只提交一次。
请求同时携带当前曲目身份，服务端及平台桥接在执行前校验；返回成功还需核对媒体位置。
仅接到命令但位置未确认时返回 uncertain，不自动重试或移动真实进度显示来伪装成功。

Windows 使用 GSMTC `TryChangePlaybackPositionAsync`（100ns tick）；Android 使用
`MediaController.TransportControls.seekTo`（ms）且检查 `ACTION_SEEK_TO`。
2026-10-15 本机网易云会话实测：seek=false，duration=0，position=0。
此客户端在当前系统接口下不能由心隅跳转，只能在网易云内部调整。

## AI 到底有没有听到声音

目前没有采集或上传音频。自动活动上下文只有歌曲信息与播放状态；用户可以主动发送
选中的歌词。模型可讨论已给出的文字与用户感受，不能把歌词理解描述成听到了旋律。
提示不再要求一律拒绝讨论，也不应反复自我解释或把每个问题都抛回用户。

真正的音频理解是后续独立链路，需要以下工作才能交付：

1. Windows 在受支持系统上用按进程的 WASAPI loopback，只捕获网易云进程树。
   Android 10+ 用 AudioPlaybackCapture 和系统 MediaProjection 授权，并限制目标 UID；
   网易云自身若禁止录音，不能绕过，也不能承诺所有设备都可用。
2. 由用户显式触发短片段分享，展示采集状态、时长和停止按钮，默认不保存音频。
   不捕获麦克风或其他应用；撤销、离开前台、超时立即结束。
3. 对接具备音乐/音频理解能力的模型。当前文本聊天适配器不能直接分析 PCM。
   必须明确模型服务商、授权与费用预算，并做真实音频验收后才能标为「已接入音频」。
4. 理解结果可以作为短期听歌上下文，但音频、识别错误与歌词文本都不能变成系统指令，
   也不能无条件写入长期记忆。保留当前安静陪伴、冷却与不打断音乐规则。

依据：[Windows 定向音频捕获](https://learn.microsoft.com/en-us/samples/microsoft/windows-classic-samples/applicationloopbackaudio-sample/)、
[Android 播放音频捕获](https://developer.android.com/media/platform/av-capture)、
[音频理解能力示例](https://ai.google.dev/gemini-api/docs/audio)、
[Windows 跳转接口](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession.trychangeplaybackpositionasync)、
[Android 播放控制](https://developer.android.com/reference/android/media/session/MediaController.TransportControls#seekTo(long))。

本轮不采集真实音乐、不调用真实付费模型。模拟播放器验证协议与状态机，
Flutter 实际渲染验证交互、布局与字体；Android 真机媒体能力仍需安装实测。
