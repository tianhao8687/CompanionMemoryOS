import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../data/automation.dart';
import '../state/automation_controller.dart';
import 'glass.dart';
import 'ui_standard.dart';

class NeteaseConnectionCard extends StatelessWidget {
  const NeteaseConnectionCard({
    super.key,
    required this.controller,
    required this.disabled,
  });
  final AutomationController controller;
  final bool disabled;

  @override
  Widget build(BuildContext context) {
    final state = controller.state;
    final enabled = state?.netease?['enabled'] == true;
    final tools = state?.neteaseTools ?? [];
    final supported = !kIsWeb && state?.supportsNetease == true;
    final android = defaultTargetPlatform == TargetPlatform.android;
    final modes = tools
        .map((t) => state!.permission(t['name'] as String))
        .toSet();
    final mode = modes.length == 1 ? modes.single : 'custom';
    return Material(
      color: Colors.white,
      borderRadius: XinYuLayout.corners,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(
                  Icons.music_note_rounded,
                  size: 28,
                  color: XinYuColors.accent,
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '网易云音乐',
                        style: XinYuLayout.body(context)
                            .copyWith(fontWeight: FontWeight.w500),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        state == null
                            ? '正在读取连接状态'
                            : !supported
                            ? '当前设备暂不支持'
                            : enabled
                            ? (tools.isEmpty ? '已启用，等待连接' : '已连接')
                            : '未连接',
                        style: XinYuLayout.note,
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                if (!enabled)
                  TextButton(
                    key: const Key('connect-netease'),
                    onPressed: disabled || !supported
                        ? null
                        : controller.connectNetease,
                    child: const Text('连接'),
                  ),
              ],
            ),
            const SizedBox(height: 16),
            const Text('找歌、播放与切歌', style: XinYuLayout.note),
            if (tools.isNotEmpty) ...[
              const SizedBox(height: 16),
              PopupMenuButton<String>(
                key: ValueKey('music-permission-$mode'),
                tooltip: '更改网易云操作权限',
                initialValue: mode,
                enabled: !disabled && supported,
                onSelected: controller.setMusicPermission,
                itemBuilder: (_) => [
                  for (final entry in const {
                    'ask': '每次操作前确认',
                    'allow': '允许自动操作',
                    'off': '不允许操作',
                  }.entries)
                    PopupMenuItem(value: entry.key, child: Text(entry.value)),
                ],
                child: Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('AI 操作权限', style: XinYuLayout.note),
                            const SizedBox(height: 4),
                            Text(
                              const {
                                'ask': '每次操作前确认',
                                'allow': '允许自动操作',
                                'off': '不允许操作',
                                'custom': '按已有规则',
                              }[mode]!,
                              style: XinYuLayout.body(context),
                            ),
                          ],
                        ),
                      ),
                      const Icon(Icons.unfold_more_rounded, size: 20),
                    ],
                  ),
                ),
              ),
            ],
            ExpansionTile(
              tilePadding: EdgeInsets.zero,
              shape: const Border(),
              collapsedShape: const Border(),
              title: Text(
                enabled ? '连接与权限详情' : '连接帮助',
                style: XinYuLayout.note,
              ),
              children: [
                Text(
                  android
                      ? '请先安装并打开网易云音乐。播放控制需要在系统中允许心隅的通知使用权；心隅仅处理网易云的媒体会话。'
                      : '请打开这台电脑的网易云音乐。暂停与切歌需要在网易云设置中开启 SMTC，然后播放一首歌。',
                  style: XinYuLayout.note,
                ),
                if (enabled) ...[
                  const SizedBox(height: 16),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      OutlinedButton(
                        key: const Key('connect-netease'),
                        onPressed: disabled || !supported
                            ? null
                            : controller.connectNetease,
                        child: const Text('重新连接'),
                      ),
                      TextButton(
                        key: const Key('disable-netease'),
                        onPressed: disabled || !supported
                            ? null
                            : controller.disableNetease,
                        child: const Text('停用连接'),
                      ),
                    ],
                  ),
                ],
                for (final tool in tools)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: RoundedChoiceField<String>(
                      key: ValueKey(
                        '${tool['name']}-${state!.permission(tool['name'] as String)}',
                      ),
                      initialValue: state.permission(tool['name'] as String),
                      label: musicToolTitle(tool['name'] as String),
                      choices: const {
                        'ask': '每次确认',
                        'allow': '允许自动调用',
                        'off': '禁用',
                      },
                      onChanged: disabled || !supported
                          ? null
                          : (value) {
                              if (value != null) {
                                controller.setPermission(
                                  tool['name'] as String,
                                  value,
                                );
                              }
                            },
                    ),
                  ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
