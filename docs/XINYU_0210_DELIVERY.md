# 心隅 0.2.10 前端交付

日期：2026-09-29—30（北京时间）。版本：`0.2.10+13`。

本页记录此前已经生成的 0.2.10 成品。9 月 30 日后续的
[统一字体调整](FONT_UNIFICATION_20260930.md)只更新源码，不包含在本页安装包与哈希中。

按用户确认的概念图完成 Android / Windows 玻璃界面：暖白底色、浅蓝与浅白消息区分、
统一尺寸的工具按钮与发送按钮、私人备注，以及设置和角色主页的配套颜色。
界面不增加发送快捷键、示例对话或“AI 伙伴”提示；引用内容没有深色竖线。
实现与离线联调证据见 [前端改版记录](FRONTEND_REDESIGN_20260929.md)。

## 安装包

用户已明确批准源码上传与手动双端构建。
[构建运行 36588474129](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36588474129)
使用源码提交 `e2184e52efcfc7e65fe8e63f7d48102fcc126d0c`，Windows / Android 打包作业均成功。
该运行的初始 Android 模拟器验收失败，记录保留，不能将整个运行称为全部通过。
没有创建新的公开 Release；工作流仍只有 `workflow_dispatch` 入口。

本机交付目录为 `dist/xinyu-local/2026-09-29-0.2.10/`：

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `XinYu-Windows-0.2.10-Setup.exe` | 33,777,241 | `0d5b2fa01a8a0184c6a483fcddbf7a719f267b5fb1cbcd43c437e0cd2b413224` |
| `XinYu-Windows-0.2.10.zip` | 42,364,295 | `e4832a651cd269f0784efa845579e8591b0c65a8534bdf9893a0c0af5cac7ff6` |
| `XinYu-Android-0.2.10-arm64.apk` | 49,337,144 | `48bc2cad0f6e0c0e8ac7822492e67b270204ebeb4d64a865a76cb093a5f097e4` |
| `XinYu-Android-0.2.10-Upgrade-arm64.apk` | 49,336,312 | `8b0e17d856acc2133ad6445f9531baa6289e8a015d906c2107dc41d385599e28` |

目录内另有 `SHA256SUMS.txt` 和 `artifacts.json`。下载的 Actions ZIP 已逐一核对 GitHub 提供的
SHA-256，解压前校验路径，再计算并保存成品哈希。Actions 产物只保留 7 天，本地文件另行保存。
Windows 免安装版需完整解压，保留相邻 `engine` 与 `data` 等运行文件，不能只移动 EXE。
安卓建议使用 `Upgrade` 包。本机保留的开发签名已核对，与已发布 0.2.9 证书一致，
证书 SHA-256 为 `e9bdcd364ad1513e8c385d6438c8ac6ccf9634c6138d2db57e18ae6da3de223a`。
升级包由云端原包在本机重新签名得到，全部 92 个 ZIP 项目名称与解压字节逐一相同；
v2 签名、16 KB 对齐、Java 桥和 SQLite FTS5 再次通过。包名保持不变，版本码由 12 升至 13，
支持相同旧签名的覆盖安装条件；本轮没有在用户手机执行升级，不宣称已验证手机上的数据保留。
GitHub 原包使用另一枚构建机开发签名，不能直接覆盖该旧版；旧签名文件没有上传。

## 检查结果

- [源码 CI 36588467337](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36588467337)：
  Ruff 检查、格式检查、Mypy 全部通过；Linux 全量 Python 测试 **1158 passed, 3 skipped**。
  最终测试配置提交 `ae5711cc3b630b8d7067d75539d207048cf44f15` 的
  [CI 36594324558](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36594324558) 也全部通过。
- 本机 Flutter 静态检查零问题，**58 项测试通过**；两端构建再次执行这些检查并通过。
- Windows 打包引擎云端隔离验收通过：`native-bundle-aa23ef1a411c4cd58dd9b776239ca258`。
- 下载后的同一 Windows 引擎在本机复验通过：`native-bundle-453d23d5213c41b68594b1bb39b1ad52`。
  验证真实进程的认证、会话持久化、同请求幂等、备份恢复、重启、数据租约与 EOF 退出。
  引擎 SHA-256 为 `06ddffca5c35ffd0ec634c044854949d411d6932a114d43f7e6bac81cbfb99f7`。
- Windows EXE 文件版本为 `0.2.10+13`。本轮未覆盖日用安装，也未操作日用数据。
- Windows 原生 GUI 自动化未通过：测试程序启动了自己的窗口、引擎与合成数据库，
  但隐藏 / 屏幕外窗口的辅助功能树只返回窗口和 Flutter 容器，无法验证输入框连接标识。
  四次本地尝试与失败证据保留：`windows-gui-626de658d2b941bb9590b3e7fb6ebd14`、
  `windows-gui-4815e0451bff474f9abb9d54a0e7bd16`、`windows-gui-f4cebb658d8c4e85b54d2d77bf254a5a`、
  `windows-gui-9762f809496e46f59405f903e86a1653`。未将进程存活或 Widget 截图冒充原生控件验收。
- Android 构建、APK 签名、16 KB ZIP 对齐、Java 凭据桥接与 SQLite FTS5 静态检查通过。
- Android 真机、Windows 中文输入法与原生性能分析未验收；没有发起真实模型调用。

所有本地进程验收使用新建的 `.agent-tests` 合成数据，测试进程结束后关闭自身启动的引擎。
离线结果证明应用流程，不证明真实模型的语言表达质量。

## Android 启动检查

实际 ARM64 APK 在 Android 15 / API 35 的独立 x86_64 模拟器上借助 ARM64 转译运行。
连接判定使用 `xinyu-local-ready` 语义标识，该标识只在真实仓库完成连接后出现，
加载、演示或连接失败不满足条件；没有重新加入可见界面提示。

- 首次运行 `android-startup-88b7f3fe4b4c49938137391a923e4373`：安装成功，启动命令超时，
  随后模拟器连接失效；没有证明首次连接成功。
- 复跑 `android-startup-44d34b8278d547bd8264b869043bbe82`：首次启动已连接真实引擎，
  已保存界面 XML 与截图；重启后 UI 导出失败且模拟器失联，整个批次仍判为失败。
- 测试配置提交 `f40187bc527cfd9928691e05a4082f56e3383930` 将已弃用的
  `swiftshader_indirect` 换为 `swiftshader`，禁用快照，并保存运行机内存、进程和内核诊断。
  配置依据 [Android 官方图形加速说明](https://developer.android.com/studio/run/emulator-acceleration)。
  这只调整模拟器环境，保留原有首次启动及重启判定，继续使用上述相同 SHA-256 的 APK。
- [启动检查 36592639128](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36592639128)：
  `android-startup-244d33d5506e44738ef303e283191bec` 仍失败，UI 导出期间模拟器失联；
  宿主机诊断未记录内存不足终止。
- [GLES 检查 36593535349](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36593535349)：
  `android-startup-0e1f8b1caefa41b98e4214b3887f8fb3` 仍失败，启动命令超时且模拟器失联，
  日志出现 `bad window surface handle`。不能据此确定是应用缺陷或模拟器缺陷。
  后续配置使用官方支持的 `-gpu software` 自动选择软件图形后端，并保留冷启动与诊断输出。
- [软件渲染检查 36594330359](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36594330359)：
  `android-startup-20f9f129e4a24c2c9296afc0671cadaa` 仍失败，模拟器失联。
  最终状态为 **Android 首次连接有成功证据，但首次启动和重启的完整验收未通过**。
  所有模拟器检查均使用云端原 APK；本地重新签名的升级包只完成静态复验和完整内容一致性检查，
  没有单独进行设备运行验收。不将升级包或模拟器结果写成真机验证通过。

原始截图、XML、日志、数据库和下载分段仅保留在被 Git 忽略的本地证据目录，不加入源码提交。
