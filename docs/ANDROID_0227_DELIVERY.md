# Android 0.2.27：手机能力与网易云更新

2026-10-18，本地交付测试 APK，版本 `0.2.27+30`，应用名「心隅·测试」，
包名 `com.xinyu.xinyu_flutter.preview`。ARM64，安装最低 Android 7；新增手机能力需要 Android 9。

## 安装包

`dist/android-0.2.27-preview/XinYu-Android-0.2.27-Preview.apk`

- 大小：70,616,829 字节（约 67.3 MiB）。
- SHA-256：`0e62f471bea12d7fc928239efbf4528da4b72d631071d049ae941343bb582603`。
- 签名证书 SHA-256：`56bc64632bbaa74030ae487179935f499390c99122521a3891cf5c3ae6589b3e`。
- 与之前本地 0.2.22 测试包的包名及证书相同，可以覆盖升级；与正式包并存、数据独立。
- 同目录保存 `delivery.json`、`SHA256SUMS.txt`、依赖来源和安装说明。

## 包含的更新

- [内置手机能力](ANDROID_PHONE_CAPABILITIES.md)：复用 droid-mcp v0.11.0，提供 24 项能力，
  接入现有聊天、权限及操作记录，可与网易云连接同时启用。
- 网易云沿用当前源码的 10 项原生 MCP 工具，包含账号连接、歌词找歌、播放状态与控制、
  歌单参考、人设音乐品味及音乐陪伴；保留 Android 自己的媒体会话和 Intent 路径。
- 包含 0.2.26 的歌单详情接口修复及当前页缺失歌曲资料补取；没有把 Windows 的后台点歌通道
  或客户端不切前台的行为套用到 Android。

在「设置 → 连接」开启需要的连接。网易云播放控制按页面引导授予通知使用权；
手机界面操作按需授予无障碍权限，亮度与勿扰分别授权。需要支持工具调用的模型。

## 构建及检查

四个缺失的 Android wheel 已补到本地 `clients/xinyu_flutter/engine/wheels/`（不提交二进制）。
版本为 pydantic-core 2.46.5、rpds-py 2026.6.3、tiktoken 0.14.0、Pillow 12.3.0。
它们来自项目先前校验过的 0.2.11 APK 依赖恢复缓存，逐字节保持原 ARM64 库与 CPython 3.13
字节码；本轮重新校验来源包与各 wheel 的 SHA-256，以及 7 个原生库的 ARM64/16 KB 对齐。
这不是本机重新编译四个第三方库。心隅当前引擎、Flutter 与 Kotlin 代码均重新构建。

- Release 编译、v2 签名、16 KB ZIP 对齐、凭据/音乐/手机 JNI 桥和 FTS5 检查通过。
- APK 内 212 项引擎文件逐项匹配本次源码/资产；Python 字节码与当前源码编译结果一致，
  包括网易云目录、歌单处理及新手机适配。169 项 Flutter/Android 构建输入与当前源码一致。
- 80 个包内原生库均为 ARM64，ELF 加载段至少 16 KB 对齐；droid-mcp 许可资产完整。
- 本轮 Flutter analyze 与 157 项测试通过。复用同一代码的上一轮 Python 全套
  1,898 passed / 1 skipped、手机与工具循环专项 41 passed、原生 6 passed。
- 真实进程批次 `49d065c7-ed4c-4487-9776-91bfe989b7de` 后端通过，语言质量未验收。
- 未在真实手机安装/控制，也没有真实模型调用。本次交付供用户安装体验，不宣称真机运行通过。
- 随后的本机 Android 15 自动化批次 `android-local-f42b6ca6081d4f5684d8572b3065bae3`：
  原始交付 APK 的 37 项运行检查通过，覆盖冷启动/重启、双 MCP 连接、系统授权往返、
  原生依赖、音量确认与去重、亮度/勿扰读回、无障碍读取/点击/输入及撤销后的拒绝执行。
  范围与复测入口见 [本机 Android 自动化测试](ANDROID_LOCAL_AUTOMATION.md)。
  网易云真实登录/播放和实体手机后台行为仍未验收。

构建目录 ID：`5c6ce7b9a98540cbb1b8f2256d34a822`，最终签名检查目录后缀为 `-preview`。
检查脚本与初次包名参数未生效的产物保留于 `.agent-tests/android-0227-delivery/`。
打包脚本新增显式 `-Preview` 参数和包名/版本核对；没有上传 GitHub 或触发远端打包。
