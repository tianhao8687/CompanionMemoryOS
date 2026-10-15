import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'focus_field.dart';
import 'focus_style.dart';
import 'glass.dart';

class FocusSetup extends StatefulWidget {
  const FocusSetup({
    super.key,
    required this.controller,
    this.proposal,
    this.onStarted,
  });
  final CompanionController controller;
  final Map<String, dynamic>? proposal;
  final VoidCallback? onStarted;
  @override
  State<FocusSetup> createState() => _FocusSetupState();
}

class _FocusSetupState extends State<FocusSetup> {
  final form = GlobalKey<FormState>();
  late final task = TextEditingController(
    text: widget.proposal?['intention'] as String? ?? '',
  );
  late final minutes = TextEditingController(
    text: '${widget.proposal?['focus_minutes'] ?? 30}',
  );
  late final rest = TextEditingController(
    text: '${widget.proposal?['rest_minutes'] ?? 5}',
  );
  bool started = false;
  @override
  void dispose() {
    task.dispose();
    minutes.dispose();
    rest.dispose();
    super.dispose();
  }

  String? _valid(String? value, int max) {
    final n = int.tryParse(value ?? '');
    return n == null || n < 1 || n > max ? '请输入 1–$max 的整数' : null;
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: widget.controller.focus,
    builder: (context, _) {
      final focus = widget.controller.focus;
      final active = focus.session != null && !focus.session!.closed;
      return Form(
        key: form,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            FocusField(
              inputKey: const Key('focus-task'),
              controller: task,
              maxLength: 160,
              label: '想做的事',
              hint: '可以留空',
              onChanged: (_) => setState(() => started = false),
            ),
            const SizedBox(height: 20),
            LayoutBuilder(
              builder: (context, bounds) {
                final stacked =
                    bounds.maxWidth <
                    MediaQuery.textScalerOf(context).scale(60) * 3 + 48;
                final options = [
                  for (final n in [15, 30, 45])
                    Semantics(
                      selected: minutes.text == '$n',
                      child: TextButton(
                        onPressed: () => setState(() {
                          minutes.text = '$n';
                          started = false;
                        }),
                        style: TextButton.styleFrom(
                          backgroundColor: minutes.text == '$n'
                              ? const Color(0xdfffffff)
                              : Colors.transparent,
                          minimumSize: const Size(0, 48),
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 12,
                          ),
                          textStyle: FocusStyle.control.copyWith(
                            fontWeight: minutes.text == '$n'
                                ? FontWeight.w600
                                : FontWeight.w500,
                          ),
                        ),
                        child: Text('$n 分钟', maxLines: 1),
                      ),
                    ),
                ];
                return GlassSurface(
                  radius: stacked ? 22 : 28,
                  blur: 16,
                  elevated: false,
                  tint: const Color(0x38ffffff),
                  padding: const EdgeInsets.all(4),
                  child: stacked
                      ? Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: options,
                        )
                      : Row(
                          children: [
                            for (final option in options)
                              Expanded(child: option),
                          ],
                        ),
                );
              },
            ),
            const SizedBox(height: 20),
            LayoutBuilder(
              builder: (context, bounds) {
                final fields = [
                  FocusField(
                    inputKey: const Key('focus-minutes'),
                    controller: minutes,
                    numeric: true,
                    validator: (v) => _valid(v, 120),
                    label: '专注',
                    unit: '分钟',
                    onChanged: (_) => setState(() => started = false),
                  ),
                  FocusField(
                    inputKey: const Key('focus-rest'),
                    controller: rest,
                    numeric: true,
                    validator: (v) => _valid(v, 60),
                    label: '休息',
                    unit: '分钟',
                  ),
                ];
                if (bounds.maxWidth <
                    MediaQuery.textScalerOf(context).scale(240)) {
                  return Column(
                    children: [
                      fields[0],
                      const SizedBox(height: 16),
                      fields[1],
                    ],
                  );
                }
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(child: fields[0]),
                    const SizedBox(width: 12),
                    Expanded(child: fields[1]),
                  ],
                );
              },
            ),
            if (focus.error != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                  focus.error!,
                  style: FocusStyle.body.copyWith(
                    color: Theme.of(context).colorScheme.error,
                  ),
                ),
              ),
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                key: const Key('focus-start'),
                onPressed: focus.busy || active || started
                    ? null
                    : () async {
                        if (!form.currentState!.validate()) return;
                        final ok = await focus.start(
                          task.text,
                          int.parse(minutes.text),
                          int.parse(rest.text),
                        );
                        if (!mounted || !ok) return;
                        FocusManager.instance.primaryFocus?.unfocus();
                        setState(() => started = true);
                        widget.onStarted?.call();
                      },
                child: Text(
                  focus.busy
                      ? '正在开始…'
                      : active || started
                      ? '正在陪你专注'
                      : '开始',
                ),
              ),
            ),
            const SizedBox(height: 12),
            const Center(child: Text('随时可以暂停或结束', style: FocusStyle.caption)),
          ],
        ),
      );
    },
  );
}
