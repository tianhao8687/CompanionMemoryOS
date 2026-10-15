import 'package:flutter/material.dart';

import '../state/companion_controller.dart';
import 'focus_style.dart';

/// Displays only completed chat replies as the companion's words.
class FocusReply extends StatelessWidget {
  const FocusReply({
    super.key,
    required this.controller,
    this.placeholder = '',
  });
  final CompanionController controller;
  final String placeholder;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: Listenable.merge([controller, controller.focus.presence]),
    builder: (context, _) {
      final presence = controller.focus.presence;
      final response = presence.response;
      final error = presence.error;
      final compact = MediaQuery.sizeOf(context).width < 600;
      final text = presence.pending
          ? '正在回应…'
          : error ?? response ?? placeholder;
      return Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (text.isNotEmpty)
            Semantics(
              liveRegion: true,
              child: Text(
                text,
                key: const Key('focus-companion-response'),
                textAlign: TextAlign.center,
                style:
                    (response != null || error != null || presence.pending
                            ? FocusStyle.body.copyWith(
                                fontSize: compact ? 16 : 18,
                              )
                            : FocusStyle.heading.copyWith(
                                fontSize: compact ? 22 : 26,
                              ))
                        .copyWith(
                          color: error == null
                              ? FocusStyle.ink
                              : Theme.of(context).colorScheme.error,
                        ),
              ),
            ),
          if (presence.pending && controller.sending)
            TextButton(
              key: const Key('focus-reply-stop'),
              onPressed: controller.cancel,
              child: const Text('停止回复'),
            ),
          if (controller.canRetryFocusInteraction)
            TextButton(
              key: const Key('focus-reply-retry'),
              onPressed: controller.retry,
              child: const Text('重试回应'),
            ),
          if (controller.settings['model_mode'] != 'api' &&
              (response != null || presence.pending))
            const Padding(
              padding: EdgeInsets.only(top: 8),
              child: Text(
                '离线规则演示 · 非模型回复',
                textAlign: TextAlign.center,
                style: FocusStyle.caption,
              ),
            ),
        ],
      );
    },
  );
}
