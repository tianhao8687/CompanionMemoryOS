# 本机测试目录迁移与清理（2026-10-19）

测试环境已迁到 `E:/XinYu-Dev`。以下是迁移与测试结束前的系统空闲空间实测，单位 GiB；
空闲量随其他程序活动变化，目录逻辑大小与实际释放空间不完全相同。

| 磁盘 | 开始时可用 | 完成时可用 | 可用量变化 |
| --- | ---: | ---: | ---: |
| C | 7.45 | 21.94 | +14.49 |
| D | 5.70 | 142.90 | +137.21 |
| E | 716.62 | 551.87 | -164.75 |

| 原路径 | 当前物理位置 | 迁移逻辑大小 |
| --- | --- | ---: |
| `D:/Tools/xinyu-sdk` | `E:/XinYu-Dev/xinyu-sdk` | 149.52 GiB |
| 仓库 `.agent-tests` | `E:/XinYu-Dev/project-tests` | 1.76 GiB |
| 仓库 `dist` | `E:/XinYu-Dev/releases` | 5.39 GiB |
| `%LOCALAPPDATA%/XinYuPrototype` | `E:/XinYu-Dev/prototype-builds` | 6.12 GiB |

四个原位置均为经过核对的目录链接，原副本已移除，历史 APK 和报告链接可继续访问。
普通文件核对数量、长度与完整 SHA-256；大型虚拟磁盘核对长度及首、中、尾三个
64 KiB 区块的 SHA-256。逐文件清单、复制日志和清理回执保存在
`E:/XinYu-Dev/migration-20261019`。

另清理了 C 盘已结束的 `pytest-139/140/141` 和过期 Flutter 临时目录，共约 0.91 GiB；
清理 D 盘 `VSBuildTemp` 旧安装临时文件约 0.54 GiB。项目源码、失败测试报告与最新 APK 保留。
共享 Android SDK/JDK 和其他项目的资料保留原位。

在此电脑测试前执行 `. ./.agent-tests/use-e-test-env.ps1`。它只设置当前 PowerShell 会话的
测试根目录、临时目录、Flutter 路径和构建输出路径；后续文件写入 E 盘。
`build_local.ps1` 支持 `XINYU_BUILD_ROOT`，显式 `-BuildRoot` 优先；其他电脑仍保留原默认行为。
真实进程测试支持 `COMPANION_TEST_ROOT`，也可显式传 `--root E:/XinYu-Dev/project-tests`。
测试驱动的链接拒绝检查保留，历史 marker 不改写。

迁移后的 Flutter 3.47.5、ADB 37.0.1 和 Emulator 37.2.12 命令检查成功。
E 盘的新构建目录完成 Flutter analyze 与 165 项测试；真实进程在 E 盘创建独立合成数据并正常退出。
最新 APK 仍为 `XinYu-Android-0.2.30-Preview.apk`，70,731,593 字节，SHA-256：
`eae63b45eb1980a79c29684b9851c29b48164e0aba606d63b3564db6cef16fa1`。
本轮没有打包新的交付 APK。
