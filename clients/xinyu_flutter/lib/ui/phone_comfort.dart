import 'package:flutter/material.dart';

import '../data/automation.dart';
import '../state/automation_controller.dart';
import 'phone_comfort_timing.dart';
import 'ui_standard.dart';

class PhoneComfortCard extends StatelessWidget {
  const PhoneComfortCard({
    super.key,
    required this.controller,
    required this.disabled,
  });
  final AutomationController controller;
  final bool disabled;

  @override
  Widget build(BuildContext context) {
    final config = controller.state!.phoneComfortConfig;
    final enabled = config['enabled'] == true;
    final active = automationList(controller.state!.phoneComfort['active']);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        SwitchListTile.adaptive(
          key: const Key('phone-comfort-enabled'),
          contentPadding: EdgeInsets.zero,
          title: Text('聊天中的手机陪伴', style: XinYuLayout.body(context)),
          subtitle: const Text(
            '允许 TA 根据聊天内容，在下面选定的范围内主动调整，不用每次下指令。只需倾诉时，也可以什么都不做。',
            style: XinYuLayout.note,
          ),
          value: enabled,
          onChanged: disabled
              ? null
              : (value) => controller.setPhoneComfort('enabled', value),
        ),
        if (enabled) ...[
          for (final item in const [
            ('media', '声音轻一点', '声音让你烦躁时，小幅降低正在播放的媒体音量。保留铃声和闹钟。'),
            (
              'screen',
              '屏幕柔和一点',
              '疲惫或屏幕刺眼时，在心隅前台读取环境光与接近状态；低光稳定、未疑似遮挡且未开启自动亮度时小幅调暗。需要修改系统设置权限。',
            ),
            (
              'interruptions',
              '留一会儿安静',
              '想暂时不被通知打断时启用优先勿扰。来电与通知按系统勿扰规则处理，需要勿扰权限。',
            ),
          ])
            SwitchListTile.adaptive(
              key: ValueKey('phone-comfort-${item.$1}'),
              contentPadding: EdgeInsets.zero,
              title: Text(item.$2, style: XinYuLayout.body(context)),
              subtitle: Text(item.$3, style: XinYuLayout.note),
              value:
                  config[item.$1] == true ||
                  (item.$1 == 'media' && config[item.$1] == null),
              onChanged: disabled
                  ? null
                  : (value) => controller.setPhoneComfort(item.$1, value),
            ),
          PhoneComfortTiming(controller: controller, disabled: disabled),
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 8),
            child: Text(
              '选中的设置会允许直接调整；点击、输入和打开应用的权限保持原样。有待处理的调整时不会叠加。说“别替我调整了”可停用。',
              style: XinYuLayout.note,
            ),
          ),
          if (config['screen'] == true &&
              ['get_light_level', 'get_proximity'].any(
                (name) => controller.state!.phonePermission(name) != 'allow',
              ))
            const Text(
              '环境感知尚未允许：关闭再开启“屏幕柔和一点”，即可允许读取。未开启时保持亮度。',
              style: XinYuLayout.note,
            ),
        ],
        if (active.isNotEmpty) ...[
          Text(
            '上次陪伴调整：${active.map((item) => item['title']).join('、')}',
            style: XinYuLayout.note,
          ),
          Wrap(
            spacing: 8,
            runSpacing: 4,
            children: [
              TextButton.icon(
                key: const Key('restore-phone-comfort'),
                onPressed: disabled ? null : controller.restorePhoneComfort,
                icon: const Icon(Icons.undo_rounded),
                label: const Text('恢复陪伴前的设置'),
              ),
              TextButton.icon(
                key: const Key('keep-phone-comfort'),
                onPressed:
                    disabled || active.any((row) => row['status'] != 'applied')
                    ? null
                    : () => controller.controlPhoneComfort('keep'),
                icon: const Icon(Icons.check_rounded),
                label: const Text('保留当前设置'),
              ),
            ],
          ),
          const Text(
            '恢复会保留你手动改过的值；选择保留后不再恢复这次调整。离开应用后不会定时恢复。',
            style: XinYuLayout.note,
          ),
          if (active.any((row) => row['status'] != 'applied'))
            const Text(
              '调整结果尚未确认，暂不能保留。可先检查手机权限，再核对恢复。',
              style: XinYuLayout.note,
            ),
        ],
        const Divider(),
      ],
    );
  }
}
