import 'package:flutter/material.dart';

import '../data/automation.dart';
import '../state/automation_controller.dart';
import 'glass.dart';
import 'ui_standard.dart';
import 'phone_comfort.dart';
import 'reply_haptics.dart';

class PhoneConnectionCard extends StatelessWidget {
  const PhoneConnectionCard({
    super.key,
    required this.controller,
    required this.disabled,
  });
  final AutomationController controller;
  final bool disabled;

  @override
  Widget build(BuildContext context) {
    final state = controller.state;
    final supported = state?.phone['supported'] == true;
    final enabled = state?.phoneServer?['enabled'] == true;
    final connected = enabled && (state?.phoneTools.isNotEmpty ?? false);
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
                  Icons.smartphone_rounded,
                  size: 28,
                  color: XinYuColors.accent,
                ),
                const SizedBox(width: 16),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '手机能力',
                        style: XinYuLayout.body(context)
                            .copyWith(fontWeight: FontWeight.w500),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        state == null
                            ? '正在读取连接状态'
                            : !supported
                            ? (state.phone['message'] as String? ??
                                  '需要 Android 9 或更高版本')
                            : connected
                            ? '已连接 · 在这台手机上执行'
                            : '未连接',
                        style: XinYuLayout.note,
                      ),
                    ],
                  ),
                ),
                if (!connected)
                  TextButton(
                    key: const Key('connect-phone'),
                    onPressed: disabled || !supported
                        ? null
                        : controller.connectPhone,
                    child: Text(enabled ? '重试连接' : '连接'),
                  ),
              ],
            ),
            const SizedBox(height: 16),
            const Text(
              '直接说“把声音调小一点”或“帮我设一个计时器”。按需开启下面的能力。',
              style: XinYuLayout.note,
            ),
            if (connected) ...[
              const SizedBox(height: 8),
              PhoneComfortCard(controller: controller, disabled: disabled),
              if (state!.phoneTools.any(
                    (tool) => tool['name'] == 'vibrate_pattern',
                  ) ||
                  state.config['reply_haptics_enabled'] == true)
                ReplyHapticsCard(controller: controller, disabled: disabled),
              for (final group in automationList(state.phone['groups']))
                _PhoneGroup(
                  controller: controller,
                  group: group,
                  disabled: disabled,
                ),
              PhonePermissionHelp(controller: controller, disabled: disabled),
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton(
                  key: const Key('disconnect-phone'),
                  onPressed: disabled ? null : controller.disablePhone,
                  child: const Text('停用手机能力'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _PhoneGroup extends StatelessWidget {
  const _PhoneGroup({
    required this.controller,
    required this.group,
    required this.disabled,
  });
  final AutomationController controller;
  final Map<String, dynamic> group;
  final bool disabled;
  static const labels = {
    'ask': '操作前确认',
    'allow': '按要求直接执行',
    'off': '关闭',
    'custom': '分别设置',
  };

  @override
  Widget build(BuildContext context) {
    final names = (group['tools'] as List).whereType<String>();
    final modes = names.map(controller.state!.phonePermission).toSet();
    final mode = modes.length == 1 ? modes.single : 'custom';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  group['title'] as String,
                  style: XinYuLayout.body(context),
                ),
              ),
              PopupMenuButton<String>(
                key: ValueKey('phone-permission-${group['id']}'),
                tooltip: '更改${group['title']}权限',
                enabled: !disabled,
                onSelected: (value) => controller.setPhoneGroupPermission(
                  group['id'] as String,
                  value,
                ),
                itemBuilder: (_) => [
                  for (final key
                      in group['id'] == 'chat_notifications'
                          ? ['ask', 'off']
                          : ['ask', 'allow', 'off'])
                    PopupMenuItem(
                      value: key,
                      child: Text(
                        group['id'] == 'chat_notifications' && key == 'ask'
                            ? '每次读取前确认'
                            : labels[key]!,
                      ),
                    ),
                ],
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    vertical: 12,
                    horizontal: 8,
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(labels[mode]!, style: XinYuLayout.note),
                      const Icon(Icons.expand_more_rounded, size: 18),
                    ],
                  ),
                ),
              ),
            ],
          ),
          Text(group['description'] as String, style: XinYuLayout.note),
        ],
      ),
    );
  }
}

class PhonePermissionHelp extends StatelessWidget {
  const PhonePermissionHelp({
    super.key,
    required this.controller,
    required this.disabled,
  });
  final AutomationController controller;
  final bool disabled;

  @override
  Widget build(BuildContext context) {
    final permissions = automationMap(controller.state?.phone['permissions']);
    return ExpansionTile(
      tilePadding: EdgeInsets.zero,
      title: Text('手机权限与使用说明', style: XinYuLayout.body(context)),
      children: [
        const Text(
          '只开启你需要的权限。界面操作需要目标应用在前台；确认时若切换了页面，会停止并要求重新读取。系统可能限制后台启动应用。',
          style: XinYuLayout.note,
        ),
        for (final entry in const {
          'write_settings': '修改系统设置 · 调整亮度',
          'dnd': '勿扰权限 · 安静陪伴',
          'accessibility': '无障碍 · 读取和操作界面',
          'chat_notifications': '通知使用权 · 陪我看消息（单独授权）',
          'overlay': '悬浮窗权限 · 后台打开应用时可选',
        }.entries)
          ListTile(
            contentPadding: EdgeInsets.zero,
            title: Text(entry.value, style: XinYuLayout.note),
            subtitle: Text(
              permissions[entry.key] == true ? '已授权，可在系统设置中撤销' : '尚未授权',
              style: XinYuLayout.note,
            ),
            trailing: TextButton(
              key: ValueKey('phone-grant-${entry.key}'),
              onPressed: disabled
                  ? null
                  : () => controller.openPhonePermission(entry.key),
              child: Text(permissions[entry.key] == true ? '管理' : '去授权'),
            ),
          ),
        const Padding(
          padding: EdgeInsets.only(bottom: 12),
          child: Text(
            '闹钟结果以系统时钟显示为准。手机陪伴开启后可按聊天内容微调已选项目；其他操作仍按你的要求执行。',
            style: XinYuLayout.note,
          ),
        ),
        TextButton(
          onPressed: () => showLicensePage(context: context),
          child: const Text('开源许可'),
        ),
      ],
    );
  }
}
