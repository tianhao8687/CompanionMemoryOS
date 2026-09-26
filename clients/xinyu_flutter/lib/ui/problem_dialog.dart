import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../data/user_problem.dart';
import 'glass.dart';

Future<bool?> showProblemDialog(
  BuildContext context,
  ValueListenable<UserProblem?> problems,
) {
  final initial = problems.value!;
  FocusManager.instance.primaryFocus?.unfocus();
  return showDialog<bool>(
    context: context,
    barrierColor: const Color(0x3033403c),
    builder: (context) => ValueListenableBuilder<UserProblem?>(
      valueListenable: problems,
      builder: (context, value, _) {
        final problem = value ?? initial;
        return Dialog(
          key: const Key('problem-dialog'),
          backgroundColor: Colors.transparent,
          insetPadding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 440),
            child: GlassSurface(
              radius: XinYuShapes.panelRadius,
              tint: const Color(0xf0f4faf5),
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      const Icon(
                        Icons.info_outline_rounded,
                        color: XinYuColors.accent,
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          problem.title,
                          style: const TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 16),
                  Flexible(
                    child: SingleChildScrollView(
                      child: Semantics(
                        liveRegion: true,
                        child: Text(
                          problem.message,
                          style: const TextStyle(fontSize: 14, height: 1.6),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),
                  Align(
                    alignment: Alignment.centerRight,
                    child: Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      alignment: WrapAlignment.end,
                      children: [
                        TextButton(
                          key: const Key('dismiss-problem'),
                          onPressed: () => Navigator.pop(context, false),
                          child: Text(problem.openSettings ? '稍后再说' : '我知道了'),
                        ),
                        if (problem.openSettings)
                          FilledButton(
                            key: const Key('problem-settings'),
                            onPressed: () => Navigator.pop(context, true),
                            child: const Text('去设置'),
                          ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      },
    ),
  );
}
