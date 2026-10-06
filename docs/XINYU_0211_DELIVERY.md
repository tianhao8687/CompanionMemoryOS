# 心隅 0.2.11 交付记录

日期：2026-10-06（北京时间）。客户端版本：`0.2.11+14`。

状态：用户已明确要求上传 GitHub、合并当前分支到 main，并更新安装包。安装包和公开
下载尚在准备中；以下检查不代表 Windows 原生界面、Android 真机或真实语言质量已通过。
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
  资源读取也正常。原失败运行 `37431005582` 保留，新的完整 CI 结果在完成后追加。

## 源码合并与安装包构建

[PR #2](https://github.com/tianhao8687/CompanionMemoryOS/pull/2) 已合入 `main`，合并提交为
`e4923ba17f8b706f116da11ae679f1bf07b9a063`。合并前 [完整 CI](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/37431387244)
通过，Linux 测试结果为 **1455 passed, 3 skipped**。

首次 [手动构建](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/37432156530) 的
Windows 作业已成功。安卓发布检查发现其固定依赖清单遗漏了小窝绘图使用的 Pillow，
该批 Android 包不用于发布。修复增加原版 Pillow 12.3.0 的 Android ARM64 源码编译与
包内模块检查，不使用桌面轮子或不符合项目最低版本的旧版二进制。

Android 中 Pillow 仅用于 RGBA 几何绘制和像素读取，不承担图片文件解码、编码或字体绘制。
该轮构建按 [Pillow 官方配置选项](https://github.com/python-pillow/Pillow/blob/12.3.0/docs/installation/building-from-source.rst)
关闭不需要的外部编解码与字体库；图片导入验证和 Flutter 展示路径不变。46 项绘图回归
通过。新 APK 检查还会拒绝缺少绘图模块或本机核心库的产物；以旧 0.2.10 包作负对照时，
Java 桥和 FTS5 检查通过，新增的 Pillow 检查按预期失败。此负对照不改变旧版本的历史结论。

Windows 构建产物保留；只重建 Android。下载入口、平台结果及成品哈希在产物生成后记录。
