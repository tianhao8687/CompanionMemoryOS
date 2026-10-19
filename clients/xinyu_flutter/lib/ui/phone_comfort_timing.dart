import 'dart:async';

import 'package:flutter/material.dart';

import '../state/automation_controller.dart';
import 'ui_standard.dart';

class PhoneComfortTiming extends StatefulWidget {
  const PhoneComfortTiming({
    super.key,
    required this.controller,
    required this.disabled,
  });
  final AutomationController controller;
  final bool disabled;

  @override
  State<PhoneComfortTiming> createState() => _PhoneComfortTimingState();
}

class _PhoneComfortTimingState extends State<PhoneComfortTiming> {
  Timer? _expiry;

  DateTime? get _until => DateTime.tryParse(
    widget.controller.state?.phoneComfortConfig['paused_until'] as String? ??
        '',
  );

  void _watchExpiry() {
    _expiry?.cancel();
    final delay = _until?.difference(DateTime.now());
    if (delay == null || delay.isNegative) return;
    _expiry = Timer(delay, () {
      if (!mounted) return;
      setState(() {});
      unawaited(widget.controller.refresh(silent: true));
    });
  }

  @override
  void initState() {
    super.initState();
    _watchExpiry();
  }

  @override
  void didUpdateWidget(covariant PhoneComfortTiming oldWidget) {
    super.didUpdateWidget(oldWidget);
    _watchExpiry();
  }

  @override
  void dispose() {
    _expiry?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final config = widget.controller.state!.phoneComfortConfig;
    final minutes = config['cooldown_minutes'] as int? ?? 3;
    final until = _until?.toLocal();
    final paused = until != null && until.isAfter(DateTime.now());
    final time = until == null
        ? ''
        : '${until.hour.toString().padLeft(2, '0')}:${until.minute.toString().padLeft(2, '0')}';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('两次联动至少间隔', style: XinYuLayout.body(context)),
        Wrap(
          spacing: 8,
          runSpacing: 4,
          children: [
            for (final value in [1, 3, 5])
              ChoiceChip(
                key: ValueKey('phone-comfort-cooldown-$value'),
                label: Text('$value 分钟'),
                selected: minutes == value,
                onSelected: widget.disabled
                    ? null
                    : (_) => widget.controller.setPhoneComfortCooldown(value),
              ),
          ],
        ),
        Text(
          paused ? '主动联动已暂停至 $time，聊天照常。' : '间隔结束后仍结合聊天判断，不会到点自动调整。',
          style: XinYuLayout.note,
        ),
        TextButton.icon(
          key: const Key('pause-phone-comfort'),
          onPressed: widget.disabled
              ? null
              : () => widget.controller.controlPhoneComfort(
                  paused ? 'resume' : 'pause',
                ),
          icon: Icon(paused ? Icons.play_arrow_rounded : Icons.pause_rounded),
          label: Text(paused ? '现在恢复联动' : '暂停联动 15 分钟'),
        ),
      ],
    );
  }
}
