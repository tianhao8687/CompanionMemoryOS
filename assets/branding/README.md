# 心隅品牌资源

2026-10-02 采用用户提供并确认的 Logo：奶白对话气泡、粉色心形气泡与环绕星光，
配合粉紫渐变底色。保留原图的构图、配色和白色留边，平台资源只调整尺寸与文件格式。

<img src="xinyu-logo.png" width="160" height="160" alt="心隅 Logo">

原始文件：[xinyu-logo.png](xinyu-logo.png)，1254 × 1254 PNG。
SHA-256：`92764c07355077f2ee29b7b4049c8c7922b6a10f7483920bf2ca498114cddf9a`。

## 已接入的位置

| 位置 | 资源 |
| --- | --- |
| Windows 窗口、任务栏与快捷方式 | `clients/xinyu_flutter/windows/runner/resources/app_icon.ico`，含 16、20、24、32、40、48、64、128、256 px |
| Windows 安装 / 卸载程序 | Inno Setup 的 `SetupIconFile` 引用同一份 ICO |
| Android 旧版启动器 | `mipmap-*/ic_launcher.png`，48、72、96、144、192 px |
| Android 自适应启动器 | `mipmap-anydpi-v26/ic_launcher.xml` + 五档 `drawable-*/ic_launcher_foreground.png`，白色背景 |
| Flutter 会话侧栏 | `clients/xinyu_flutter/assets/branding/xinyu-logo.png`，256 px，界面显示 32 逻辑像素 |
| 网页品牌标识与页签 | `companion_agent/web/branding/` 中的 Logo、ICO、32 px PNG 与 180 px 触屏图标 |
| 项目介绍 | 根目录 README 展示原图 |

Android 自适应图标采用 108 dp 图层，将含原有白边的完整原图置于中央 72 dp。
实际彩色标识约 61 dp，位于中央 66 dp 安全区域内，供不同启动器遮罩裁切。
依据：[Android 自适应图标规范](https://developer.android.com/develop/ui/compose/system/icon_design_adaptive)。
Windows 多尺寸 ICO 同时满足 [Inno Setup 图标尺寸建议](https://jrsoftware.org/ishelp/topic_setup_setupiconfile.htm)。

角色头像仍由角色资料管理；安卓状态栏通知仍使用适合单色显示的通知符号。
目前交付平台为 Windows / Android，未改动其他平台模板。

## 重新生成

在仓库根目录运行下列命令。开发环境需要 Pillow；本次生成使用 Pillow 12.3.0。
所有输出已纳入源码，正常构建客户端无需安装 Pillow。

```powershell
.\.venv\Scripts\python.exe clients/xinyu_flutter/tool/prepare_brand_assets.py
```

脚本只读取原图，生成 Flutter / 网页的 PNG、Windows ICO 和安卓各密度图标。
不会重绘原图、裁掉白边或覆盖角色头像。Android XML 和安装脚本的引用随源码维护。

## 交付范围

本轮接入本地源码与项目文档，尚未推送 GitHub，未重打安装包或发布 Release。
现有 0.2.9 公开测试版及本地 0.2.10 安装包不包含新 Logo。

## 本地检查（2026-10-02）

- 原图与上传文件逐字节一致；全部派生 PNG 可解码，尺寸符合上述清单。
- Windows `LoadImageW` 成功读取 ICO 的全部 9 档尺寸。
- Android SDK 36 的 AAPT2 成功编译项目资源并用隔离校验清单链接，解析出五档 PNG 与自适应 XML。
  这是资源检查，未构建或安装完整 APK。
- Flutter analyze 通过；原有 58 项测试通过。实际字体下的 3 项布局导出通过，
  9 张预览保存在 `dist/frontend-logo-20261002/`；已查看 Windows 侧栏、Android 会话抽屉和网页显示。
- Ruff 通过，Mypy 的 126 个源码文件通过。
- Python 全量首轮为 1158 通过、1 失败、2 跳过。失败的
  `test_temporal_recall_uses_memoryos_calendar_windows` 原先把“四天前”始终视作本月，
  在月初会与实际日历冲突。改用固定样本日期和同一 `as_of`，保持原来的召回断言；
  整个 `test_experience_layer.py` 复测 27 项通过。修正后未再次重跑完整 Python 套件。
- 网页真实进程交互通过：`b3aae1ca-db1f-4546-8839-7133075826e8`。
- 离线聊天真实进程：`a9054bbf-c6f9-4616-bdc5-d058f8429566`，后端流程通过；
  语言质量仍为 blocked（需要另行授权的真实模型评审），退出码 2，不记作语言验收通过。

原始成功与失败证据仅保留在忽略目录 `dist/frontend-logo-20261002/checks/` 和对应 `.agent-tests/` 中。
本轮未运行原生 Windows / Android 安装后的界面验收，也未调用在线模型。

## 本机桌面图标更新（2026-10-05）

当前运行目录 `dist/xinyu-current-20261005/XinYu` 已将品牌 ICO 写入原生启动程序的
`IDI_APP_ICON`（资源 ID 101）。这补齐了复用旧启动程序时仍显示 Flutter 默认图标的问题。
源代码中的 Windows 资源、安装程序和快捷方式仍引用同一套品牌图标。

检查确认 EXE 内九档图标与源 ICO 一致，代码、数据段及其他资源未变；
重新启动新版 Flutter 客户端后，实际窗口标题栏已显示心隅 Logo。
原启动程序副本和检查记录保存在忽略的构建/检查目录中。
本次只更新本机运行版，没有重新生成安装包或发布 GitHub 产物。
