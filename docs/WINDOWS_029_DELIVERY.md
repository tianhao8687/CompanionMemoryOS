# Windows 0.2.9 安装与交付记录

2026-09-27，用户在查看本地检查结果后明确要求更新 Windows 安装包并上传 GitHub。
本次只手动构建 Windows，Android 沿用已测试的 0.2.9 APK，没有再次云端打包。

Windows 现包含此前聊天搜索、引用/复制/收藏/多选、表情包、记忆手账、纪念日约定、
共同回忆、角色主页、头像/背景、阅读位置及常驻回到底部按钮等功能，保留玻璃外观与圆润选项。
本次自定义说话示例和多轮接话调整见 [0.2.9 功能与检查记录](ANDROID_029_DELIVERY.md)。
Windows 不新增 Android 的后台主动通知机制。

## 安装文件

交付目录：`dist/xinyu-local/2026-09-27-0.2.9/`。

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| `XinYu-Windows-0.2.9-Setup.exe` | 33,730,288 | `01eff9f1a2aa1e1afc87e0d7e64076f9589301926891ea1a656941b61fdb9a9f` |
| `XinYu-Windows-0.2.9.zip` | 42,314,161 | `7540611904411144e2fa66d4f40bdaf5dcda2bd473e37edacb8ed7f0444879ac` |
| `XinYu-Android-0.2.9-arm64.apk` | 52,547,980 | `2364ccc103b8468db2cdb475d6395e9a56315cf695635a0988ab7db4a87a0ad4` |

Windows 10/11 x64 运行安装程序即可；升级时先退出旧程序，直接覆盖安装，无需先卸载。
安装器版本为 `0.2.9`，客户端版本为 `0.2.9+12`。安装器 AppId 保持不变：
`{EF131C2B-CB1C-4F28-A916-DAB1B227A474}`。
程序默认位于 `%LOCALAPPDATA%\Programs\XinYu`，用户数据仍在独立的 `%LOCALAPPDATA%\XinYu\data`。
免安装版需要完整解压并运行 `XinYu/xinyu_flutter.exe`；随包带有引擎，不需要另装 Python。

## 构建与检查

源码提交：`73108e51ffdad84f72c6e51650f6d2870a1bb311`，分支 `codex/local-apps-20260925`。

- [源码 CI 36294776533](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36294776533) 通过。
- [手动 Windows 构建 36294790704](https://github.com/tianhao8687/CompanionMemoryOS/actions/runs/36294790704) 通过；
  `target=windows`，所有 Android 任务跳过。本次仅这一轮打包。
- 本地 Python 951 项通过、2 项跳过，Mypy、Ruff、格式检查通过；Flutter analyze 与 50 项测试通过。
  这些是构建前同一功能源码的检查，不将文档补充视为重新测试应用。
- 下载的 Actions 归档 SHA-256 与 GitHub artifact digest 一致。安装后逐一核对 **852 个文件**与免安装包一致。
- 冻结引擎 SHA-256：`534042b8d5ab67d1d134ecfd7d1b186e16aa48335910fee36f4f590408fcf165`。

| 运行 ID | 实际结果 |
|---|---|
| `native-bundle-02c70ed1c4044712ab4bb5a208be7d73` | Actions 随包引擎测试通过 |
| `native-bundle-8de34656b2fe4842bf32544f9a513d83` | 本机运行下载的冻结引擎通过：认证、请求幂等、持久化、备份/恢复、异常拒绝、EOF 与实例互斥 |
| `windows-upgrade-029` | 实际安装旧版 0.2.0，播种合成聊天、设置和记忆，直接覆盖安装 0.2.9；聊天 ID、角色设置、记忆及来源证据保留，新字段保存与真正重启恢复通过 |
| `windows-ui-029` | 实际安装后的图形窗口启动并连接引擎；旧聊天、新语气字段、玻璃外观和回到底部按钮显示正常；设置切换、字号预览/保存、SQLite 和重启核对通过，正常关闭后窗口及其引擎退出 |
| `windows-clean-install-029` | 实际全新安装 0.2.9，新数据库和随包引擎启动通过；仅移除测试安装，合成数据库保留 |

**验收边界：** Windows 原生语气字段的键盘自动输入未能验证。Computer Use 的键盘输入没有可见效果，
UIA `set_value` 返回 `0x80004005`，因此不将它记作文本编辑通过。
新字段的 Flutter 控件编辑、真实 HTTP 保存/清空/重启已在前一批通过；本次 Windows 验证了字段显示和随包服务保存。
没有实际调用付费模型，真实语言自然度尚未评审；Android 真机结果不由 Windows 构建代替。

所有数据均在独立 `.agent-tests/github-upload-029/` 目录生成；未访问或复制日常聊天库。
本次 UI 控件、数据库和安装日志留在忽略目录，不提交原始截图、对话或数据库。
下载第一次单连接过慢，改为校验完整哈希的分段下载；清理脚本首次误假设卸载器固定为
`unins000.exe`，快速重新安装实际为 `unins001.exe`，已改为验证目录后读取注册的卸载器并重跑通过。
保留首次失败说明，没有将失败覆盖为成功。

安装包构建继续保持 `workflow_dispatch` 手动入口；推送代码不会自动打包。
安装版、免安装版和已有 Android APK 已发布至
[心隅 0.2.9 GitHub Release](https://github.com/tianhao8687/CompanionMemoryOS/releases/tag/xinyu-v0.2.9)，
同时提供安装说明与 SHA-256 校验和。发布前逐个核对 GitHub asset digest 和大小，
发布后检查公开下载链接。源码保留在专用分支，未合并默认分支。
