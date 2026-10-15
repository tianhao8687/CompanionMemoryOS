import 'package:flutter/material.dart';

import '../data/focus.dart';
import '../state/companion_controller.dart';
import 'glass.dart';
import 'focus_style.dart';

class FocusStatus extends StatelessWidget {
  const FocusStatus({
    super.key,
    required this.controller,
    required this.openFocus,
  });
  final CompanionController controller;
  final VoidCallback openFocus;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: controller.focus,
    builder: (context, _) {
      final focus = controller.focus, session = focus.session;
      if (session == null || session.settled) return const SizedBox.shrink();
      return Container(
        key: const Key('focus-status'),
        margin: const EdgeInsets.fromLTRB(14, 8, 14, 0),
        padding: const EdgeInsets.fromLTRB(12, 4, 4, 4),
        decoration: BoxDecoration(
          color: const Color(0xd9edf1f4),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Row(
          children: [
            const Icon(
              Icons.timelapse_rounded,
              size: 18,
              color: XinYuColors.accent,
            ),
            const SizedBox(width: 8),
            Expanded(
              child: TextButton(
                onPressed: openFocus,
                child: Text(
                  '${controller.companionDisplayName} · ${session.label}  ${focusTime(focus.seconds)}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: FocusStyle.caption,
                ),
              ),
            ),
            IconButton(
              tooltip: session.actionLabel,
              onPressed: focus.busy ? null : () => focus.act(session.action),
              icon: Icon(
                session.paused
                    ? Icons.play_arrow_rounded
                    : session.phase == 'focus_done'
                    ? Icons.coffee_outlined
                    : Icons.pause_rounded,
              ),
            ),
            IconButton(
              tooltip: '结束专注',
              onPressed: focus.busy ? null : () => focus.act('finish'),
              icon: const Icon(Icons.close_rounded),
            ),
          ],
        ),
      );
    },
  );
}

Future<void> showFocusNoticeSettings(
  BuildContext context,
  CompanionController controller,
) => showDialog<void>(
  context: context,
  builder: (context) => Theme(
    data: FocusStyle.theme(context),
    child: AlertDialog(
      scrollable: true,
      title: const Text('专注提醒'),
      content: SizedBox(
        width: 340,
        child: ListenableBuilder(
          listenable: controller.focus,
          builder: (context, _) => Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const Text('到时间提醒一次'),
                subtitle: const Text('在应用内轻提示。关闭后仍能查看计时状态。'),
                value: controller.focus.preferences['focus_notice'] != 'off',
                onChanged: controller.focus.busy
                    ? null
                    : controller.focus.notice,
              ),
              const SizedBox(height: 16),
              const Text(
                '切出应用不会打断计时。退出应用或系统挂起时，暂不发送系统通知。',
                style: FocusStyle.caption,
              ),
              if (controller.focus.error case final String error)
                Text(
                  error,
                  style: FocusStyle.body.copyWith(
                    color: Theme.of(context).colorScheme.error,
                  ),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('完成'),
        ),
      ],
    ),
  ),
);
