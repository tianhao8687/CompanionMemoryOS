# 心隅 0.2.11 交付记录

日期：2026-10-06（北京时间）。客户端版本：`0.2.11+14`。

状态：源码已合入 `main`，Windows 安装版、免安装版和 Android APK 已更新为 0.2.11。
公开入口：[心隅 0.2.11 测试版](https://github.com/tianhao8687/CompanionMemoryOS/releases/tag/xinyu-v0.2.11)。
Windows 随包引擎检查通过；Windows 原生界面本轮未测，Android 运行验收和真实语言质量未通过。
打包仍只允许手动触发，源码推送不会自动构建安装包。

## 此版本内容

- 回忆小窝：像素房间、AI 回忆选材与物件绘制、来源查看、物件收纳及精选合成展示素材。
- Windows / Android Logo 与应用图标、统一中文字体、玻璃界面及私人备注。
- 情感浓度配置、静态聊天表达规则分离、当前任务与默认回复目标的区分。
- 记忆检索、索引并发、来源与版本链、长对话上下文预算的修复及相应回归。

聊天口吻调整仍有失败：真实 DeepSeek 回复仍会出现用户否定的短剧式表达。本版本不宣称
已解决该语言问题，也未加入无效的额外改写调用；见 [实测记录](CHAT_VOICE_REPAIR_20261006.md)。

## 发布前本地检查

- Ruff、格式检查通过；Mypy 检查 139 个源文件通过。
- Flutter analyze 无问题，62 项 Widget / 状态测试通过。
- Python 全套初次检查：1455 通过、2 跳过、1 失败。失败为旧测试仍要求在普通更正时注入
  默认回答目标；按已实现的“普通聊天不注入默认任务”行为更新该断言，继续保留冲突清除、
  证据链与诊断目标检查。语义更正、当前状态、输入预算和情侣聊天相关的 109 项复验通过。
- Edge 真实网页控件、完整流和落库对应检查通过：`6477659b-f52a-4d94-a76a-eac7bc166c58`。
- 已排除本地凭证、测试对话、数据库、截图和原始生成提示词；发布的像素素材是应用资源。
- 统一 Python 格式时检查了已纳入 Git 文件清单的 AST，未改变语义。
- 首次 GitHub CI 在 Linux 类型检查中发现测试工具的 Windows DLL 声明问题；改用可静态
  识别的系统分支后，本地 `mypy --platform linux` 和 `--platform win32` 均通过，Windows
  资源读取也正常。原失败运行 `37431005582` 保留，新的完整 CI 结果见下文。

## 源码合并与安装包构建

[PR #2](https://github.com/tianhao8687/CompanionMemoryOS/pull/2) 已合入 `main`，合并提交为
`e4923ba17f8b706f116da11ae679f1bf07b9a063`。合并前 [完整 CI](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/37431387244)
通过，Linux 测试结果为 **1455 passed, 3 skipped**。

首次 [手动构建](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/37432156530) 的
Windows 作业已成功。安卓发布检查发现其固定依赖清单遗漏了小窝绘图使用的 Pillow，
该批 Android 包不用于发布。修复增加原版 Pillow 12.3.0 的 Android ARM64 源码编译与
包内模块检查，不使用桌面轮子或不符合项目最低版本的旧版二进制。
该批后续被主动取消，不能将整批构建记为通过；Windows 成功产物保留使用。

Android 中 Pillow 仅用于 RGBA 几何绘制和像素读取，不承担图片文件解码、编码或字体绘制。
该轮构建按 [Pillow 官方配置选项](https://github.com/python-pillow/Pillow/blob/12.3.0/docs/installation/building-from-source.rst)
关闭不需要的外部编解码与字体库；图片导入验证和 Flutter 展示路径不变。46 项绘图回归
通过。新 APK 检查还会拒绝缺少绘图模块或本机核心库的产物；以旧 0.2.10 包作负对照时，
Java 桥和 FTS5 检查通过，新增的 Pillow 检查按预期失败。此负对照不改变旧版本的历史结论。

Android 打包依赖修复提交为 `b5b70081919c9c78f08a9d106bc9aadb27ac78e0`；其
[源码 CI](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/37433514390) 通过。
仅重新手动构建 Android：[运行 37433613988](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/37433613988)。
原生 wheel 和 APK 构建作业通过，后续模拟器运行作业失败。Windows 与 Android 的应用版本均为 `0.2.11+14`。

## 成品与平台结果

本地文件保存在 `dist/xinyu-local/2026-10-06-0.2.11/`。从 GitHub 下载的两组构建产物 ZIP
均按 GitHub 提供的 SHA-256 验证，再提取最终文件；没有将中断的下载或漏依赖的旧 APK 用于发布。

| 平台 | 本次实际检查 | 未验证范围 |
| --- | --- | --- |
| Windows | 安装程序版本 0.2.11、应用版本 0.2.11+14；云端和本地随包引擎真实进程检查通过 | 本轮原生图形窗口、安装程序实际安装、日用数据覆盖升级未测 |
| Android | 包名不变、版本码 14、仅 ARM64；Pillow、Java 桥和 FTS5 检查通过；v2/v3 签名及 16 KB ZIP 对齐通过 | 模拟器运行验收未通过；真机安装、覆盖升级及数据保留未测 |
| 语言质量 | 保留此前真实 DeepSeek 失败记录，本次打包没有额外模型调用 | 用户指出的短剧式句式尚未解决 |

本地 Windows 随包引擎运行 ID：`native-bundle-bdd1a3c335444276a926960c4c8783dc`。
测试仅使用新建合成目录，覆盖进程握手、HTTP 授权、持久化、备份和退出；未打开日用数据库。
引擎 SHA-256：`f9826c31254d8d28bd82b120d2af06cecfcd2b7cd89574d3b1d1470207a2a46d`。

Android 15 模拟器运行 ID：`android-startup-bc74c988221340aaacc7d7a2f38783dd`。
实际 APK 已安装且 Activity 返回启动成功，首次 UI 快照尚未出现引擎连接标记；随后
`uiautomator dump` 失败，清理时模拟器 TCP 5554 拒绝连接。未完成引擎就绪和重启检查，
因此结果保持 **failed**。已有证据不能证明真实手机上的运行结果，也没有足够日志确定模拟器断开的根因。
失败回执、UI 快照、作业及主机日志保留在本地测试目录与该 Actions 运行的证据产物中，不提交到源码。

Android 使用与公开 0.2.9 及本地 0.2.10 升级包相同的开发证书重新签名，证书 SHA-256 为
`e9bdcd364ad1513e8c385d6438c8ac6ccf9634c6138d2db57e18ae6da3de223a`。
重签名没有改变 103 个非签名 ZIP 条目的内容；最终 APK 未在设备上运行。密钥库不上传。
Windows 程序未作商业代码签名。升级说明和校验文件随 Release 附件提供。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `XinYu-Windows-0.2.11-Setup.exe` | 51923289 | `b07d2c9aa646055d94a650c3ce4b7c4e95921c10a6d34ab9801963db573e181d` |
| `XinYu-Windows-0.2.11.zip` | 67035194 | `302a7a840eb6b97244defcf728140077bf2a5d3c8169e7c63842b67f43c0e8af` |
| `XinYu-Android-0.2.11-arm64.apk` | 67666725 | `1f91f450b08890f402cb9112c62c173a301597b2b96a1c29b5ad0ae5d0180773` |
