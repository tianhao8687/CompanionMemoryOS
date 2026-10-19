import 'package:flutter/material.dart';

import '../state/automation_controller.dart';
import 'ui_standard.dart';

class ReplyHapticsCard extends StatelessWidget {
  const ReplyHapticsCard({
    super.key,
    required this.controller,
    required this.disabled,
  });
  final AutomationController controller;
  final bool disabled;

  @override
  Widget build(BuildContext context) {
    final state = controller.state!;
    final enabled = state.config['reply_haptics_enabled'] == true;
    final supported = state.phoneTools.any(
      (tool) => tool['name'] == 'vibrate_pattern',
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SwitchListTile.adaptive(
          key: const Key('reply-haptics-enabled'),
          contentPadding: EdgeInsets.zero,
          title: Text('随回复表达触感', style: XinYuLayout.body(context)),
          subtitle: const Text(
            '特别开心、感动或认真表达想念时，允许 TA 在回复完成时短拍两下，约 0.36 秒。根据对话判断，不是每条消息都震动。',
            style: XinYuLayout.note,
          ),
          value: enabled,
          onChanged: disabled || (!supported && !enabled)
              ? null
              : controller.setReplyHaptics,
        ),
        if (enabled)
          const Padding(
            padding: EdgeInsets.only(bottom: 8),
            child: Text(
              '仅前台、解锁且未通话时触发；至少间隔 20 秒。说“别震了”也能关闭。触感强弱由手机决定。',
              style: XinYuLayout.note,
            ),
          ),
        if (!supported)
          const Text('当前版本未提供触感能力，请更新并重新连接。', style: XinYuLayout.note),
        if (enabled && state.phonePermission('vibrate_pattern') != 'allow')
          const Text('触感权限已暂停；重新开启此开关即可恢复。', style: XinYuLayout.note),
        const Divider(),
      ],
    );
  }
}
