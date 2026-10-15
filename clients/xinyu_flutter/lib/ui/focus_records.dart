import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'focus_field.dart';
import 'focus_style.dart';

Future<void> showFocusRecords(
  BuildContext context,
  CompanionController controller,
) async {
  await controller.focus.refresh();
  if (!context.mounted) return;
  await showDialog<void>(
    context: context,
    builder: (context) => AlertDialog(
      scrollable: true,
      title: const Text('活动记录'),
      content: SizedBox(
        width: 400,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('这里记录开始、暂停和结束的时间。任务进展由你决定是否留下。'),
              const SizedBox(height: 16),
              if (controller.focus.history.isEmpty) const Text('还没有活动记录。'),
              for (final item in controller.focus.history)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(
                    (item['intention'] as String).isEmpty
                        ? '留了一段时间'
                        : item['intention'] as String,
                  ),
                  subtitle: Text(
                    '计时 ${((item['elapsed_seconds'] as num) / 60).floor()} 分钟 · ${item['phase'] == 'ended' ? '已结束' : '时间到了'}',
                  ),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('关闭'),
        ),
      ],
    ),
  );
}

Future<void> showFocusProgress(
  BuildContext context,
  CompanionController controller,
) => showDialog<void>(
  context: context,
  builder: (_) => _FocusProgress(controller: controller),
);

class _FocusProgress extends StatefulWidget {
  const _FocusProgress({required this.controller});
  final CompanionController controller;
  @override
  State<_FocusProgress> createState() => _FocusProgressState();
}

class _FocusProgressState extends State<_FocusProgress> {
  final text = TextEditingController();
  late String request = widget.controller.focus.requestId();
  late final sessionId = widget.controller.focus.session!.id;
  String? error;
  bool busy = false;
  @override
  void dispose() {
    text.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    scrollable: true,
    title: const Text('留下一点进展'),
    content: SizedBox(
      width: 400,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          FocusField(
            inputKey: const Key('focus-progress-input'),
            controller: text,
            maxLength: 500,
            minLines: 2,
            maxLines: 5,
            enabled: !busy,
            label: '想留住的那句话',
            onChanged: (_) {
              request = widget.controller.focus.requestId();
            },
          ),
          if (error != null)
            Text(
              error!,
              style: FocusStyle.body.copyWith(
                color: Theme.of(context).colorScheme.error,
              ),
            ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: busy ? null : () => Navigator.pop(context),
        child: const Text('先不写'),
      ),
      FilledButton(
        onPressed: busy
            ? null
            : () async {
                if (text.text.trim().isEmpty) {
                  setState(() => error = '写下想留住的那一点进展就好。');
                  return;
                }
                setState(() {
                  busy = true;
                  error = null;
                });
                try {
                  await widget.controller.focus.saveProgress(
                    text.text,
                    request,
                    sessionId,
                  );
                  if (context.mounted) Navigator.pop(context);
                } catch (e) {
                  if (mounted) setState(() => error = e.toString());
                } finally {
                  if (mounted) setState(() => busy = false);
                }
              },
        child: Text(busy ? '正在保存…' : '收进记忆手札'),
      ),
    ],
  );
}
