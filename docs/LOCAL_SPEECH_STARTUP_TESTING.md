# 本地语音启动优化与日常中文测试

2026-10-19。源码已修改；本轮没有构建或安装 APK，没有调用云端语音或收费模型。
证据目录为 `E:/XinYu-Dev/project-tests/local-voice-fast-20261019/`，首轮接入证据仍保留在
`E:/XinYu-Dev/project-tests/local-voice-20261019/`。模型、录音、缓存及临时文件使用 E 盘。

## 改动

- 打开「说给我听」时预加载已下载的模型，不开启麦克风、不联网。同一面板内继续说话时复用模型，
  每段创建新的识别流，清空分段文字、PCM 未完整采样点和队列，避免上一段混入下一段。
- 点击开始后，麦克风与模型加载并行；加载期间在内存中保存开头音频，最多 20 秒。
  模型就绪后顺序送入，不截掉开头。界面提示“已经开始录音，正在准备出字，开头会保留”。
  提前停止也接收尾帧并等到最终结果；取消则丢弃本段，关闭面板后的回调不能恢复录音或文字。
- 下载完成或首次完整检查后，在应用私有模型目录保存 `.verified.json`。
  固定资源清单、文件大小、修改/变更时间匹配时复用校验记录；文件变化或记录缺失、损坏、过期时
  重新计算固定 SHA-256。应用重启无需重复读取全部约 190 MiB 权重。
- 关闭面板、切后台或收到内存压力时释放模型。预热不在后台常驻；尚在进行的原生初始化完成后
  释放其资源，避免在分配内存中途强杀。停止收音不需要等待模型初始化结束。
- 保留原模型、CPU 2 线程、4 路 `modified_beam_search`、端点参数及最终补齐策略，
  仍是免费的 sherpa-onnx 1.12.14 本地推理，没有额外账号、服务或标点润色模型。

源文件：`local_asr_worker.dart` 管理模型/识别流；`local_speech_input.dart` 管理收音与暂存；
`speech_models.dart` 管理下载/校验记录；`voice_input.dart` 和语音面板负责状态及生命周期。
它们位于 `clients/xinyu_flutter/lib/` 下的 `data`、`state`、`ui` 目录。

## 启动实测

Windows 使用真实 `VoiceInput → LocalSpeechInput → LocalAsrWorker → sherpa-onnx` 路径，
资源检查也真实执行；只替换录音插件的权限与麦克风接口，将一段 3.6 秒真人 WAV 每 200 ms 注入。
测量从调用开始录音到相应事件，不含系统权限弹窗、真实麦克风启动及界面动画。
三个场景各运行一次，是开发机对照样例，不是跨设备平均值或 P95。
“冷”表示新建识别器，不保证操作系统文件缓存为空。优化后的冷启动未提前预热。

| Windows 完整软件路径 | 优化前首次录音 | 优化后首次录音 | 优化后同面板再次录音 |
| --- | ---: | ---: | ---: |
| 录音接口就绪（麦克风替身） | 3563 ms | 8 ms | 3 ms |
| 点击至首次非空文字 | 3988 ms | 2160 ms | 440 ms |
| 点击至最终文字 | 7263 ms | 3792 ms | 3773 ms |
| 停止至最终文字 | 61 ms | 60 ms | 57 ms |

三次最终转写一致。8/3 ms 只说明代码不再阻塞麦克风等待模型，不能当成手机实际启动时间。
首次原生模型加载并没有消失；录音可以先开始，文字仍要等模型准备好。
同机模型首次 SHA 校验 1735 ms，重新打开资源管理器后使用校验记录为 5.3 ms。
下载本身已校验；旧安装没有记录或资源变化时仍需支付一次完整校验成本。
证据：`startup-pipeline-results.json`、`model-validation-timing.json`、`startup-pipeline.log`。
此前尚未加入持久校验记录的完整流程也保留在 `startup-pipeline-before-receipt-*`。

Android 在自有只读 API 35 x86_64 模拟器中运行相同版本/参数的 C API 原生探针：

| Android 原生部分 | 测量 |
| --- | --- |
| 优化前每段重建模型，3 次 | 5732、4894、3304 ms |
| 复用方案的首次模型加载 | 3509.8 ms |
| 后续 40 段仅创建新识别流 | 0.856–3.367 ms，中位数 1.153 ms |
| 41 段后的原生进程峰值内存 | 约 508 MiB |

这里测的是原生加载/创建识别流，不包含 Flutter、麦克风、权限或完整 App 的启动及内存。
没有把“1 ms 创建识别流”当作手机“1 ms 出字”。ARM64 探针已编译，未在 ARM64 真机运行。
自有模拟器已关闭，`android-native-results.json` 的 `owned_emulator_stopped` 为 `true`。

## 日常中文录音与评分

真人数据来自 [StepFun 的 StepEval-Audio-360](https://huggingface.co/datasets/stepfun-ai/StepEval-Audio-360)，
数据卡声明 Apache-2.0；使用专业人员录制/标注的公开中文样本，不是用户日常聊天数据库。
固定修订 `a1e5d8f34e5e5bd22073c8e96279832cd1105769`；原始音频归档 SHA-256：
`f7e9f043765500c6f6940ae58a55cf226ddfdde533099f4765bc40d2710d82d3`。

推理前选定 20 段日常/情绪表达：朋友生病、被领导批评、放假旅游、开心、考试失落等。
选择的 `(id, turn)` 为 `(13,1/2), (16,2), (17,2), (19,1/2/3/4/5/6),
(24,1/2), (25,2/3/5/6/7), (30,3), (31,3/6)`，共 286 个评分字符。
清单、参考文本、音频 SHA 和预设目标在 `corpus-protocol.json`、`corpus-manifest.json`，
参考文字没有依据识别输出修改，也没有送入识别器作为提示。

原始 48 kHz WAV 用 97 tap Kaiser 窗低通（截止 7.2 kHz、补偿群延迟）重采样到 16 kHz PCM16，
不裁剪、不归一化。另取其中 4 段分别降低到 15% 音量、加入固定随机种子的 10 dB 白噪声，
加上 3 秒纯静音，共 29 段。低音量和噪声是人工变换，不能当成真实轻声或现场噪声采集。

额外使用电脑已有离线 Huihui/Kangkang 两个声音合成 6 句中文，共 12 段、186 个评分字符，
覆盖疲惫、失望、改口日期时间、朋友聚餐、歌名和犹豫停顿。合成语音单列，不混入真人指标。
没有调用网络 TTS；参考与协议见 `synthetic-manifest.json`、`synthesis-protocol.json`。

评分为字符编辑距离 / 参考字符数（CER）。先做 NFKC、大小写归一、移除标点和空白，
不纠正同音字、不将数字词强行改成数字、不调用聊天模型修正。识别失败按空输出计入漏字。
该小样本用于开发回归，不能外推为所有中文聊天的准确率。

| 语料 | 数量 / 评分字符 | Windows 原模型复用 | Android 原生复用 |
| --- | ---: | ---: | ---: |
| 真人原始录音 | 20 / 286 | 8 字编辑，CER **2.8%** | 9 字编辑，CER **3.1%** |
| 模拟低音量 | 4 / 59 | 2 字编辑，CER 3.4% | 1 字编辑，CER 1.7% |
| 模拟 10 dB 白噪声 | 4 / 59 | 7 字编辑，CER **11.9%** | 7 字编辑，CER **11.9%** |
| 离线合成日常语音 | 12 / 186 | 3 字编辑，CER 1.6% | 3 字编辑，CER 1.6% |
| 纯静音 | 1 | 空输出 | 空输出 |

真人原始录音两端均为 14/20 段归一化后完全匹配。Windows 29 段在优化前每段加载与优化后
复用模型两种实现中，**原始转写逐段完全一致**，没有为了降低等待改变识别结果。
所有实际推理均返回结果，失败数为 0；证据见 `quality-results.json`、`corpus-original.json`、
`corpus-reuse.json`、`corpus-synthetic.json` 和 `android-corpus.json`。
该批音频以无等待方式注入以检查输出，不能用其首字时间宣称实时延迟；实时节奏只见上面的流程测试。

能正确处理本组朋友生病、旅行和考试失落等完整句子；仍有“在/再”“它/他”、省略“嗯”、
增加或漏掉虚词的问题。没有接额外标点模型，文字可能缺标点。发送前保留编辑确认。
尚未验证真机麦克风、远场、真实轻声/噪声、方言、长时间持续使用或广泛专名。

## 更小模型的对照

另外试了约 26.3 MB 的
[streaming Zipformer small CTC](https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01)，
其链接的[原始模型](https://huggingface.co/csukuangfj/icefall-streaming-zipformer-small-ctc-zh-2025-04-01)声明 Apache-2.0。
同一 20 段真人语料出现 27 字编辑，CER **9.4%**，完全匹配仅 7/20，模拟噪声 CER 27.1%。
电脑冷加载约 1.85 秒。考虑到本轮小模型对照的漏字/错字增加，产品继续保留原模型；
小模型仅留在 E 盘实验目录，未加入客户端依赖或下载入口。
结果和原始转写保存在 `ctc-candidate-quality.json`、`corpus-ctc-candidate.json`。

## 回归与复现

Flutter 全量 **214 项通过**，包括预热不请求录音权限、反复录音复用模型、冷启动保留开头、
加载中关闭、加载中停止后只送一次尾帧、文件同大小损坏识别、校验记录损坏/过期回退，
以及原有草稿保护与窄屏大字体布局。首次 analyze 报告 4 处缺括号的风格提示，修复后无问题。
这些插件/状态测试使用替身，不用来声称真实麦克风效果。
Ruff、mypy（173 个源文件）通过。Python 全量 **2015 通过、1 跳过**，用时 421 秒；
有 1 条已有 Starlette/httpx 弃用提示，没有测试失败，完整输出见本轮 `pytest.log`。

真实应用隔离进程编号 `12d0e77c-9905-4d3b-8d6c-e6c42a2f9658`：后端流程通过，
使用离线聊天模型，聊天语言质量仍为 `blocked`（预期退出码 2）。未调用在线聊天模型。
语音的本地真实推理结果与这项后端离线流程分开记录。

从英文 E 盘客户端测试副本运行，避免中文 Windows 路径影响 Flutter 原生测试：

```powershell
. 'E:/XinYu-Dev/project-tests/use-e-test-env.ps1'
$env:PUB_CACHE = 'E:/XinYu-Dev/xinyu-sdk/pub-cache'
$env:XINYU_ASR_NATIVE_DIR = "$env:PUB_CACHE/hosted/pub.dev/sherpa_onnx_windows-1.12.14/windows"
flutter analyze
flutter test --no-pub
dart run tool/probe_speech_corpus.dart <模型目录> <corpus-manifest.json> <结果.json> reuse 0
```

探针要求清单中的 WAV 校验值匹配，单个文件不超过 20 秒，最多 80 段，每段超时 45 秒；
`fresh` 模式每段重新加载，`reuse` 复用模型，最后参数 `200` 可改为每 200 ms 送包。
参考文字仅供单独评分，传给模型的只有 PCM。Windows 复用探针源码在
`clients/xinyu_flutter/tool/probe_speech_corpus.dart`；Android 多段探针为同目录的
`probe_local_asr_android.c`，用 1.12.14 官方头文件/库和 NDK 编译，不需要 APK。

本次完整流程测试脚本、固定清单、重采样脚本、独立 CER 评分脚本与完整日志保存在 E 盘证据目录：
`client/tool/startup_pipeline_test.dart`、`prepare_corpus.py`、`score_corpus.py`、`run_android_native.py`。
公开录音和原始测试对话不加入源码仓库；失败或被否决方案的证据也保留。
