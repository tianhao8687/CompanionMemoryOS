# 免费本地语音输入

2026-10-19：源码已替换豆包商业 ASR，未打包或发布新的 APK。
同日 Windows 0.2.31 已纳入该实现及启动优化，成品验证见 [Windows 交付记录](XINYU_0231_DELIVERY.md)。

## 用户体验与免费条件

聊天输入框的麦克风打开「说给我听」。首次点击「下载免费语音资源」，联网下载约
190 MiB；完成后识别在当前手机或电脑上运行，无需语音账号、API Key、充值或自租服务器。
资源下载好后点「开始说话」，边说边更新文字；停止后可以修改或继续说，点「放进输入框」
才插入当前光标位置，最后仍由用户手动发送。原草稿或会话变化时拒绝覆盖。

只在明确点击下载时访问模型网站，打开面板和识别过程均不下载资源。支持进度、取消和手动重试；
重试复用已经完整下载并校验通过的文件，不承诺未完成文件的断点续传。
下载时按固定字节数和 SHA-256 校验，在应用私有目录保存校验记录；后续文件大小、修改时间、
变更时间及固定资源清单均匹配时复用记录，避免每次重复读取约 190 MiB 文件。
记录缺失、损坏、过期或文件元数据变化时重新计算 SHA-256，校验失败的资源不进入原生识别器。
模型存放在应用支持目录的 `voice/zipformer-zh-en-2023-02-20-int8` 子目录。
资源总计 199,056,205 字节，不含客户端和原生库；存储、运行内存与电量由用户设备承担。

每次录音最多一分钟，可以继续补充；切后台、关闭面板和录音中断会停止麦克风，错误时保留已显示文字。
录音只在内存中处理，应用不保存或上传音频。未发送的文字不进入聊天记忆；发送后使用原有聊天路径，
若用户选择在线聊天模型，发送的文字仍会交给该模型。这次仅做转写，不从语气推断情绪或触发手机操作。

## 开源组件与许可证

| 内容 | 选用与来源 |
| --- | --- |
| 本地推理 | [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)，Apache-2.0；Flutter 绑定及所有平台原生包固定 `1.12.14` |
| 原始模型 | [pfluo / pkufool 中英双语流式 Zipformer](https://huggingface.co/pfluo/k2fsa-zipformer-chinese-english-mixed)，发布者声明 Apache-2.0 |
| ONNX 权重 | [Fangjun Kuang 转换版本](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20)，声明 Apache-2.0；固定修订 `98590b7ed6443e77b714204da2757d75e1a642f4` 的文件内容 |
| 国内下载源 | [原发布者的 ModelScope 镜像](https://modelscope.cn/models/pkufool/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20)，公开下载不需要账号；即使分支变化也必须匹配源码内校验值 |
| 录音 | [record 7.1.2](https://pub.dev/packages/record/versions/7.1.2)，BSD-3-Clause，复用 PCM 流，不使用系统语音识别服务 |

使用上游现成的 int8 encoder / joiner、原始 decoder / tokens，没有重新训练或修改权重。
框架与模型的归属、完整 Apache-2.0 文本随 [许可证资源](../clients/xinyu_flutter/assets/licenses/zipformer.txt)
登记到应用许可证页；包管理器继续收集第三方包许可证。未随应用分发上游训练集或测试录音。

## 实现

`record` 输出 16 kHz 单声道 PCM16，直接交给 Dart isolate 中的 sherpa-onnx，使用 CPU 2 线程、
`modified_beam_search` 和 4 条活动路径。UI 线程不加载或推理模型；停顿后分段继续，
停止录音时接收插件尾帧、补齐模型右上下文，再取最终结果。
打开语音面板时预加载模型，不申请麦克风权限或开始录音；同一面板内复用模型，
每段录音创建全新的识别流。结束或取消时清空本段音频、文字状态并释放录音器，
关闭面板、切后台或收到内存压力时释放模型。不会在后台常驻预热。
本地初始化、读取权限、关闭面板和延迟返回均受会话代次保护，避免退出后重新开启麦克风或覆盖新草稿。

资源检查、权限允许后即可开始收音，模型冷加载与录音并行；开头的 PCM 在内存中暂存，
模型就绪后按原顺序送入识别器，界面明确提示正在录音、等待出字。暂存上限为 20 秒音频。
提前停止仍会接收尾帧并等待本次识别，关闭面板则立即取消本段，迟到回调不能带回文字。
手机速度不足时有限制音频队列，
明确停止并保留文字，不静默丢音或切换云端。普通话和英语自动混合识别，无需语言服务账号。
未接入额外标点模型或聊天模型润色，原始文字可能缺标点、错字或专名，发送前可编辑。

删除了豆包凭据界面、语音 HTTP / WebSocket 路由、商业协议实现、显式 WebSocket 依赖和
`speech_to_text` 备选。旧设置中的已知 `voice_provider` 值在读取时兼容移除，其他设置不变。

版本选择经过实际调用：本机下载的 `sherpa_onnx_windows 1.13.8` 原生库请求 ORT API 28，
但配套 ONNX Runtime 报告仅支持 API 1–17，实际初始化崩溃。改为同版本的 `1.12.14`
绑定与原生包后完成下列识别。失败日志仍保留，不能只升级 Dart 包并让平台库浮动版本。

## 首轮接入测试（启动优化前）

本轮证据根目录：`E:/XinYu-Dev/project-tests/local-voice-20261019/`。
模型、缓存、测试临时文件与输出使用 E 盘。没有生成 APK、安装手机应用或调用付费语音服务。

- Windows：用应用同一个 `LocalAsrWorker`，以 200 ms 节奏输入上游 4 段真实中英混说 WAV，
  均得到最终文字；另测 2 秒纯静音，没有输出文字。完整输入摘要、原始转写、失败和时延分别保存于
  `asr-protocol.json`、`asr-results.json`、`asr-probe.log` 与原生诊断日志。
- Android：在自有只读 API 35 x86_64 模拟器运行 C API 探针，使用同一模型、版本和解码参数，
  识别上述 `0.wav`、`3.wav` 成功。结果见 `android-native-results.json`，测试后已关闭自有模拟器。
  这是原生库真实推理，不是 Flutter 整机录音流程或 ARM64 真机验收。
- Flutter 全量 **209 项通过**，包括资源下载、完整性拒绝、取消重试、PCM 分包、停止尾帧、
  延迟启动取消、识别修正、原草稿/会话保护和窄屏大字体布局。录音插件测试使用合成音频与解码替身，
  不把这部分当实际麦克风准确率测试。最后的小幅界面文案调整后，语音专项 **18 项通过**。
- 用应用的下载器访问真实 ModelScope 镜像，分 4 次 Range 请求取回约 13.2 MiB 的 decoder，
  长度、SHA-256 与后续离线检查通过。首次运行发生下载中断，随后显式重跑通过，原因未确定；
  两次证据保存在 `download-smoke-initial-results.json` 与 `download-smoke-results.json`。
  这项抽样验证没有重复下载全部 190 MiB，也不保证任意网络条件下下载成功。
- Python 全量初跑 **2014 通过、1 失败、1 跳过**。失败的旧角色表达测试按空行切 JSON，
  将紧邻的提示词也读进 JSON；改为解析 JSON 对象自身，内容相等、隔离、重启与清除断言保留。
  修复后角色表达、旧设置迁移、本地运行时及上下文预算相关 **21 项通过**；未将局部重跑称为第二次全量通过。
- Ruff、mypy（173 个源文件）与 Flutter analyze 通过。Android 原始 `record_android` / `sherpa_onnx_android`
  插件库编译通过，NDK API 24 的 x86_64 与 ARM64 探针均编译通过；未执行 APK 构建。
  ARM64 的 sherpa / ORT 两个库 LOAD 段为 16 KiB 对齐，这不替代整包兼容性检查。
- 真实应用隔离进程运行编号 `3aa5cc20-ad28-45f0-93e9-3b1759339c29`：后端流程通过；
  本次使用离线聊天模型，语言质量仍为 `blocked`（预期退出码 2），没有新增聊天模型调用。

| 实测项目 | Windows 电脑，同一 Dart worker | Android x86_64 模拟器，C API 探针 |
| --- | --- | --- |
| 模型冷加载 | 2.14–2.37 秒 | 3.03–6.60 秒 |
| 首次非空文字 | 首包音频后 0.45–1.30 秒 | 未按实时节奏测量，不报首字时间 |
| 停止后最终结果 | 38–53 毫秒 | 无节奏整体解码 8.83–10.05 秒音频用时 1.43–1.80 秒 |
| 进程内存峰值 | 整个 Dart 测试进程约 687–699 MiB | 原生探针进程约 509 MiB |

冷加载数值不含资源哈希检查、权限等待；首字时间不含冷加载，不能当点击按钮后的总等待。
内存也不是模型本体大小或完整心隅运行占用，手机还会有 Flutter、Python 和界面开销。
不同平台的混说转写存在差异；上游演示音频没有本轮独立人工标注，不能据此给出准确率。
这一轮尚未验证真实手机麦克风、轻声、噪声、长时间使用、方言、专名和情绪陪伴语料。
不宣称达到豆包准确率、所有设备可即时启动或通过真机验收。

## 启动优化与日常中文测试

后续已完成预加载、模型复用、录音与加载并行，以及持久化校验记录。
用 20 段公开真人日常/情绪中文录音对照优化前后，电脑端原始转写全部一致；
该小样本字符错误率为电脑 2.8%、Android 模拟器原生库 3.1%。
另测 4 段模拟低音量、4 段模拟噪声、静音及 12 段本地合成语音，分别统计。
电脑完整流程（真实模型、模拟麦克风）点击至首字由约 3.99 秒降为 2.16 秒，
同一面板内再次录音约 0.44 秒；Android 首次原生加载仍约 3.5 秒，复用时无需重复加载。
这不是手机端完整录音响应时间或真机验收，详见
[启动优化和中文语音测试记录](LOCAL_SPEECH_STARTUP_TESTING.md)。

## 复现入口

先在客户端执行 `flutter pub get`，常规检查使用 `flutter analyze`、`flutter test`。
Windows 语音库测试可运行：

```powershell
$env:XINYU_ASR_NATIVE_DIR = '<Pub缓存>/sherpa_onnx_windows-1.12.14/windows'
dart run tool/probe_local_asr.dart <模型目录> <含0.wav至3.wav的证据目录>
```

`XINYU_ASR_NATIVE_DIR` 应指向同时包含 `sherpa-onnx-c-api.dll` 与 `onnxruntime.dll` 的实际目录，
打包后的应用使用平台库默认路径，不需要用户设置它。测试录音从上述固定修订的 `test_wavs/`
下载到测试目录；模型四个文件必须匹配 `lib/data/speech_models.dart` 中的 SHA-256。

不生成 APK 的 Android 库检查，从仓库根目录运行：

```powershell
clients/xinyu_flutter/tool/check_voice_native.ps1 -Output <E盘英文测试目录> -FlutterSdk <Flutter目录>
```

可加 `-Offline` 使用已有 Gradle 依赖；脚本仅编译库。Android C API 验证源码位于
`clients/xinyu_flutter/tool/probe_local_asr_android.c`，使用 v1.12.14 的官方 C API 头文件和
同版本 Android 库，以 NDK 编译后放入自有测试模拟器运行，不安装 APK。
