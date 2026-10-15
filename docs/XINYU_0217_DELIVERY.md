# 心隅 0.2.17 交付记录

日期：2026-10-15。当前客户端主版本为 `0.2.17+20`，源码合入 `main`，
发布标签为 `xinyu-v0.2.17`。[下载当前版本](https://github.com/tianhao8687/CompanionMemoryOS/releases/latest)。
本版仍为公开测试版本；旧 Release 及附件由本版替代，提交历史和历史验证记录保留。

## 本版功能

- Windows / Android 本机网易云连接，共用六个 MCP 工具和原有授权、操作账本。
- 「一起听」独立界面：播放时旋转唱片、滚动歌词、桌面侧栏对话和手机键盘适配；
  支持安静陪伴及有节制的主动发言，不引入音频模型或歌曲音频上传。
- 明确请求时可凭歌词找歌并交给网易云；不确定的版本展示候选卡片。
  发送打开请求与已确认播放分别显示，会员及版权权限仍由网易云客户端处理。
- 有效陪听中的个人分享与歌曲关联，进入既有 `SHARED_MOMENT` 记忆。
  支持跨对话、重启后召回，更正、遗忘和来源限制；仅播放或歌词引用不自动成为个人经历。
- 陪我专注、回忆小窝界面调整、统一字体字号与间距、合并设置和应用连接入口。

实现与使用说明：[网易云 MCP](NETEASE_MUSIC_MCP.md)、[歌词点歌](LYRIC_SONG_REQUESTS.md)、
[自动同步](NETEASE_AUTO_SYNC.md)、[陪听记忆](LISTENING_MEMORY.md)、[界面标准](UI_STANDARD.md)、
[陪伴专注](FOCUS_CURRENT_UI.md)。

## 安装文件

| 文件 | 大小（字节） | SHA-256 |
| --- | ---: | --- |
| `XinYu-Windows-0.2.17-Music.zip` | 69,067,406 | `d8c3c1e327ce2ef3a15f1b5d016d69bdfc6815ad95add8a0ff164c672d96d522` |
| `XinYu-Android-0.2.17-Preview.apk` | 70,118,007 | `dc11093f7521e10f18f5d970fa79f337f144e847dd9906fc8a49457d4ca55596` |

Windows：退出旧窗口，完整解压 ZIP，运行 `XinYu/xinyu_flutter.exe`；保留整个目录结构。
内置引擎，无需安装 Python。本次提供免安装包，未生成新的 Setup 安装向导。

Android：Android 7.0+ / ARM64，版本 `0.2.17-preview`、versionCode 20。
包名 `com.xinyu.xinyu_flutter.preview`、名称「心隅·测试」，沿用本地预览版测试签名。
可覆盖同签名的 0.2.16 预览版；与旧 GitHub 公开版并存、数据独立，不会直接覆盖旧版数据。
可通过现有备份导出/恢复功能迁移，真实设备升级与迁移仍待验证。

先安装官方网易云客户端并播放歌曲；Windows 开启 SMTC，Android 按引导授予通知使用权。
Windows 自动进度读取已针对网易云 3.1.41 验证，其他版本可能需要兼容；
拖动歌曲进度取决于客户端是否提供可用的 seek 能力。歌词服务不可用或没有时间戳时会降级显示。

## 验证结果与边界

- Python 全量 **1,628 通过、1 跳过**；最终收紧模糊指代后，陪听与自然记忆专项 **50 通过**。
- Ruff 检查与格式检查通过，Mypy **153 个源文件**通过。
- 歌词点歌版本的 Flutter analyze 与 **130 项测试**通过。本次仅变更客户端版本号，
  Windows / Android release 构建通过，未重复执行 Flutter 全量测试。
- 真实应用隔离进程 `f30a0896-09d0-4a67-89bc-e76e324f2490`：**11 步后端检查通过**。
  无真实模型批次，语言质量保持 `blocked`，不能当作自然语言效果通过。
- Windows 冻结引擎 `native-bundle-f9918ff979de4b848389c00629f71c7a`：通过；
  引擎 SHA-256 为 `d5b92ce740cf57b1a755e2926b9009416a52699fe74d1a47903720558e119fd4`。
- Windows ZIP **956 项**与展开目录逐文件一致。APK v2 签名、16 KB 对齐、音乐桥接、
  SQLite FTS5、Pillow 和七个关键 Python 源文件与仓库一致性检查通过。
- 本次没有真实模型调用、真实播放器动作或日用数据库测试；Android 真机运行、
  最新包的原生图形窗口、真实模型点歌及回忆表达仍待验收。

发布附件提供 `INSTALL.md`、`SHA256SUMS.txt` 和 `delivery.json`。
交付目录为 `dist/music-player-20261015-v6/`；原始测试数据仅保存在忽略的 `.agent-tests/`，不上传 GitHub。
安装包始终手动构建，普通 push 仅运行源码 CI。
