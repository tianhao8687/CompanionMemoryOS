# 字体统一 · 2026-09-30

## 当前状态

本轮是 Windows / Android Flutter 前端源码和真实组件预览更新。
用户查看字体及界面检查结果后，明确要求上传 GitHub 并更新 Markdown 文档与项目介绍。
上传范围包括字体实现、许可、项目 README、客户端说明和交付状态；使用现有
`codex/local-apps-20260925` 分支。已有 0.2.10 安装包尚未包含本轮字体，安装包仍仅手动构建。
本轮不改变 Python 引擎或数据结构，也没有发起真实模型调用。

## 排版

- 两端、全部页面使用随应用内置的 **Noto Sans SC**，取消按操作系统选择主字体。
- 正文使用 400 字重；界面标题、选中项使用 500 字重。表情插画内的重字保留 700。
- 中文采用字体原生字间距；输入框和消息正文共用一处样式：窄屏 16、桌面 18 个逻辑像素，行高 1.5。
- 保留应用字号偏好及系统无障碍缩放；emoji 和字体不包含的字符仍由系统回退。
- 预览工具加载实际打包字体，不再依赖 Windows 系统安装的微软雅黑。

字体原文件未修改，包含 30,890 个 Unicode 字符映射、100–900 字重轴，
覆盖当前界面源码中的全部 560 个不同汉字。没有按预览文本裁剪字体。
文件大小为 17,772,300 字节，所有字重复用一份文件；无需启动时联网下载。
上游版本、哈希、许可见 [字体资产说明](../clients/xinyu_flutter/assets/fonts/README.md)。
完整 OFL 许可随字体纳入应用资源，打包后的两份文件哈希与原文件一致。

## 验证

- `flutter analyze --no-pub`：通过。
- `flutter test --no-pub --reporter expanded`：58 项通过。
- 加载内置字体后复跑现有 9 个界面测试文件：49 项通过，包含窄屏、长备注、
  放大字号、键盘与输入法、消息操作、设置和手账。
- 真实字重检查：400 / 500 / 700 的 `fontWeight` 渲染与显式设置变量轴逐像素一致；
  三种字重笔画覆盖量递增，未依赖假粗体。
- `flutter test tool/layout_preview.dart`：3 项通过，导出 8 张真实组件图片，
  已检查两端聊天、设置、角色主页，以及 Windows 备注和消息组件。
- `git diff --check`：通过。

本机证据在忽略目录 `dist/frontend-fonts-20260930/`，实际字体界面复跑日志为
`checks/font-loaded-widget-tests.log`。临时检查入口在客户端 `build/`，未加入产品代码。
初次临时入口把网络单元测试也合并进 Widget binding，导致 2 项请求被 Flutter
测试框架固定返回 400；该失败日志保留于 `checks/font-loaded-tests.log`。
修正临时入口后仅合并 9 个界面测试文件；网络测试保留其原有独立环境，常规全套已通过。

以上为 Flutter 测试引擎内的渲染和交互结果，不代表新安装包、Android 真机或
Windows 原生窗口已经验收。截图使用隔离合成数据；没有读取日常聊天数据库。

## GitHub 上传前复核与项目介绍

根 README 改为先介绍心隅客户端、聊天与记忆功能、下载入口，再介绍记忆 SDK；
此前 Agent 版本说明保留为历史记录。客户端说明、前端改版与交付文档互相补充链接，
明确区分最新字体源码、已构建的 0.2.10 成品及公开的 0.2.9 测试版。
本轮修改的 7 份 Markdown 文档中，74 处本地链接检查通过。

GitHub 仓库简短介绍同步为：

> 心隅 XinYu｜本地优先的 AI 陪伴与长期记忆项目。Windows / Android 玻璃聊天界面，
> 自定义角色、私人备注、记忆更正与遗忘，支持 DeepSeek 等模型 API。Flutter + Python + SQLite。

上传前 Ruff 检查、309 份 Python 文件格式检查、126 个源文件的 Mypy 检查通过。
Python 全量首轮为 **1 failed, 1158 passed, 2 skipped**：
`test_automatic_preferences_cross_chats_and_negation_supersedes` 在异步索引发布前读取
`memory_embeddings` 数量；原测试单独复跑通过。修复只调整该测试：有界等待原有后台线程，
核对生效记忆的具体 ID 已被索引，并在 `finally` 关闭自己的索引器。
没有改变生产索引、提取或召回逻辑，也没有放宽原来的跨会话偏好检查。相关 31 项测试通过。
首轮、单项复跑及修复后结果分别保留在本机 `checks/publish-pytest.log`、
`checks/publish-pytest-targeted.log`、`checks/publish-functional-repaired.log`。
修复后的全量复核为 **1159 passed, 2 skipped**（282.68 秒），日志为
`checks/publish-pytest-repaired.log`。初次失败证据保留，不以单项通过替代全量结果。

真实应用离线场景运行 ID 为 `88de16e3-4634-4cfb-b0f8-c431eac13083`：
按项目规定执行 `tests/scenarios/chat_quality.json`，后端流程通过；语言质量为 `blocked`，
命令按预期返回 2。本轮未获得真实模型批次授权，因此未调用在线模型；
没有将离线成功解释为语言质量通过。

## 微信字体的核实范围

能确认腾讯官方 [WeUI 样式](https://github.com/Tencent/weui/blob/master/dist/style/weui.css#L55-L58)
采用 `system-ui, -apple-system, "Helvetica Neue", sans-serif`，即优先系统字体。
WeUI 是网页界面库，不能据此认定各版本原生微信聊天窗口的字体。
本次未找到覆盖这些原生客户端的官方字体清单，因此不把微软雅黑、苹方或
Noto Sans SC 中的某一款称为统一的“微信聊天字体”。
