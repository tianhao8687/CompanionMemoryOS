# Android 0.2.29：聊天中的手机陪伴

2026-10-19（北京时间）完成本机交付。APK 为 `0.2.29+32`，ARM64，应用名「心隅·测试」，
包名 `com.xinyu.xinyu_flutter.preview`，大小 70,715,205 字节。

SHA-256：`a2ea5e7d8dad15fe087cdac221ef05511295db14be4e144b8e944dac4df26c08`。
交付目录：`dist/android-0.2.29-preview`，包括 APK、安装说明、测试报告与校验资料。

## 本次功能

在「连接 → 手机能力 → 聊天中的手机陪伴」一次开启并选择范围后，主聊天模型可以根据
本轮聊天与上下文，决定是否适度降低媒体音量、调暗屏幕或开启优先勿扰，无需逐次操作指令。
模型也可以只陪伴、不操作。具体条件、幅度与权限说明见 `docs/PHONE_COMPANIONSHIP.md`。

默认关闭，首次开启仅选媒体音量；屏幕与勿扰分别开启并授予相应系统权限。
提供 30 分钟冷却、当前原文依据、读写间状态核对、拒绝停用、保存原值与恢复按钮。
恢复包含自动亮度模式，并保留用户已手动改变的值。没有后台定时恢复。
升级时刷新内置手机工具接口，保留已有权限配置；不随升级开启主动陪伴或界面操作。

## 验证结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 最终原始 APK，Android 15 模拟器 | **41 项通过** | `android-local-57f4aade79014167b1e70db842d2bdbd` |
| Python 全套，聊天上下文修复后 | **1,920 通过、1 跳过** | `.agent-tests/phone-comfort-full-final.xml` |
| 最终手机陪伴、容量与升级专项 | **27 项通过** | `.agent-tests/phone-comfort-release-checks.xml` |
| Flutter 全套 / analyze | **163 项通过 / 通过** | `.agent-tests/build-0229-final.log` |
| Flutter 手机专项 | **13 项通过**，覆盖 320/768/1024/1440 宽度 | `.agent-tests/phone-comfort-flutter.log` |
| Android 原生单元检查 | **8 项通过** | `.agent-tests/android-0229-delivery/native-phone-tests.xml` |
| Ruff / mypy | **通过**；mypy 170 个源文件 | `.agent-tests/phone-comfort-ruff-final.log`、`phone-comfort-mypy-final.log` |
| APK 源码、依赖与签名 | **通过**；213 个引擎输入、170 个客户端输入、80 个 ARM64 ELF；签名及 16KB 对齐通过 | `dist/android-0.2.29-preview/delivery.json` |

全套 Python 回归包含上下文容量修复；随后补充的原生接口升级刷新由最终 27 项专项覆盖。
没有把初次失败算成通过，也没有修改容量测试的原有预算或断言。

41 项模拟器检查覆盖冷启动与重启、实际 Flutter 手机/音乐连接、陪伴开关与范围选择、
停用、系统权限授予与撤销、Python/JNI/SDK、音量确认和去重、亮度与勿扰读回、
无障碍读取/点击/输入/长按/滑动，以及密码遮罩和系统区域拦截。

新增的 `real_chat_phone_companion` 在**安装后的最终 APK 内**运行真实聊天、ToolHub、
独立 SQLite 和原生 Android 设置路径：用脚本模型为“我眼睛好酸，屏幕晃得我难受”选择
调暗屏幕，核对亮度下降与手动模式，再恢复并核对自动亮度模式；继续验证冷却与
“别替我调整了”的持久停用。这里没有替换手机桥或伪造系统设置结果。

独立真实进程验收 `e42df3a9-0303-40b9-9d46-3c0a035acdc5`：backend passed，
language_quality blocked；8 轮、8 次离线适配器调用、0 次在线模型调用。
该结果只证明应用流程，不能当作语言质量评审通过。

## 限制

- 情绪时机由用户配置的聊天模型判断。本轮用脚本模型验证执行与拒绝路径，
  **没有对真实模型在自然对话中的判断效果做评审**，没有调用真实在线模型。
- 不是后台常驻控制服务；退出应用或到点后不会自动恢复。已有恢复信息会保留到下次使用。
- 自动恢复限于同一对话、最近 6 小时的调整；恢复按钮与明确恢复请求可处理较早的记录。
- 本轮没有真机验证，没有登录网易云账号，也没有重测实际音乐播放。
  此前音乐实测路径和模拟器限制仍见 `docs/ANDROID_0228_AUTOMATION.md`。

## 保留的失败与修复

- 初轮全套为 1,919 通过、1 失败、1 跳过。关闭陪伴时仍注入说明，加上增长的通用工具说明，
  触发了原有 16K 长消息容量边界。现已按需注入并压缩通用说明，原测试与后续全套均通过。
- 初始 APK 批次 `android-local-83343908425c4a67b42f3b66a2f989e6` 的 41 项通过，
  但其 SHA-256 为 `2c0ee2c…b0a79`，不是最终交付 APK；原包保留在
  `.agent-tests/android-0229-delivery/pre-budget-fix.apk`。
- 最终 APK 的第一次批次 `android-local-a5584ca672434a1288b8f410720b6bd9`：
  原生检查通过，界面开关点击未生效。记录显示控件仅在底部部分可见；驱动改为滚到完整
  可见范围、点击一次并轮询核对 checked 状态，不重复切换。上述最终批次全部通过。
- 中文路径下 Flutter 分析器报 LSP JSON 截断；改用已有英文路径构建目录，analyze 通过。
  分词数据下载停滞时停止本次拥有的构建子进程，改用此前已校验的同版缓存。
- 所有失败日志保留在 `.agent-tests`。模拟器由受控驱动创建并关闭；未使用日常数据库或真实手机。

复跑入口为 `clients/xinyu_flutter/tool/smoke_android_local.py` 与
`clients/xinyu_flutter/tool/build_android_probe.py`。测试探针单独打包，不向产品 APK 添加测试入口。
