import 'dart:convert';

import 'package:flutter/material.dart';

import '../data/automation.dart';
import '../state/automation_controller.dart';
import 'glass.dart';
import 'ui_standard.dart';

class ConnectedAppAction extends StatelessWidget {
  const ConnectedAppAction({
    super.key,
    required this.controller,
    required this.action,
    required this.disabled,
  });
  final AutomationController controller;
  final Map<String, dynamic> action;
  final bool disabled;

  @override
  Widget build(BuildContext context) {
    final pending = action['status'] == 'pending';
    final id = action['id'] as String;
    final arguments = automationMap(action['arguments']);
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: Material(
        color: XinYuColors.incoming,
        borderRadius: XinYuLayout.corners,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                controller.state?.actionTitle(action) ?? '应用操作',
                style: const TextStyle(fontWeight: FontWeight.w500),
              ),
              const SizedBox(height: 6),
              Text(
                automationStatus(action['status'] as String?),
                style: const TextStyle(
                  color: XinYuColors.muted,
                  fontSize: 14,
                  height: 1.6,
                ),
              ),
              if (action['created_at'] is String)
                Text(
                  _time(action['created_at'] as String),
                  style: const TextStyle(
                    color: XinYuColors.muted,
                    fontSize: 14,
                    height: 1.6,
                  ),
                ),
              if (pending) ...[
                const SizedBox(height: 12),
                if (arguments['action'] == null)
                  Text(
                    _description(arguments),
                    style: XinYuLayout.body(context),
                  ),
                ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  title: const Text('查看操作参数', style: XinYuLayout.note),
                  children: [
                    SelectableText(
                      const JsonEncoder.withIndent('  ').convert(arguments),
                      style: XinYuLayout.note,
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    FilledButton(
                      key: ValueKey('approve-$id'),
                      onPressed: disabled
                          ? null
                          : () => controller.decide(id, 'approve'),
                      child: const Text('确认并继续'),
                    ),
                    OutlinedButton(
                      key: ValueKey('deny-$id'),
                      onPressed: disabled
                          ? null
                          : () => controller.decide(id, 'deny'),
                      child: const Text('拒绝'),
                    ),
                  ],
                ),
              ] else ...[
                ExpansionTile(
                  tilePadding: EdgeInsets.zero,
                  title: const Text('查看参数与结果', style: TextStyle(fontSize: 14)),
                  children: [
                    Align(
                      alignment: Alignment.centerLeft,
                      child: SelectableText(
                        const JsonEncoder.withIndent('  ').convert({
                          'parameters': arguments,
                          'result': action['result'],
                        }),
                        style: const TextStyle(fontSize: 14, height: 1.6),
                      ),
                    ),
                  ],
                ),
                if (action['status'] == 'succeeded' &&
                    !(action['tool_name'] as String? ?? '').startsWith('app_'))
                  TextButton(
                    key: ValueKey('resume-$id'),
                    onPressed: disabled
                        ? null
                        : () => controller.decide(id, 'resume'),
                    child: const Text('继续尚未完成的回复'),
                  ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  String _description(Map<String, dynamic> args) {
    if (args['query'] is String) {
      return '在网易云搜索「${args['query']}」，显示 ${args['limit'] ?? 5} 个结果。';
    }
    if (args['song_id'] != null) return '在网易云打开歌曲，歌曲 ID：${args['song_id']}。';
    if (args['action'] != null) {
      return controller.state?.actionTitle(action) ?? '请查看操作参数。';
    }
    return args.isEmpty
        ? '读取应用状态。'
        : const JsonEncoder.withIndent('  ').convert(args);
  }

  String _time(String raw) {
    final date = DateTime.tryParse(raw)?.toLocal();
    if (date == null) return raw;
    String two(int value) => value.toString().padLeft(2, '0');
    return '${date.month}月${date.day}日 ${two(date.hour)}:${two(date.minute)}';
  }
}
