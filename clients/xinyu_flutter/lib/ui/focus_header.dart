import 'package:flutter/material.dart';

import 'focus_style.dart';

/// Equal side regions keep both companion pages' titles on the same centerline.
class FocusPageHeader extends StatelessWidget {
  const FocusPageHeader({
    super.key,
    required this.title,
    required this.backLabel,
    this.backKey,
    this.actions,
  });

  final String title, backLabel;
  final Key? backKey;
  final Widget? actions;

  @override
  Widget build(BuildContext context) {
    final compact = MediaQuery.sizeOf(context).width < 600;
    final iconOnly = compact || MediaQuery.textScalerOf(context).scale(15) > 22;
    return Padding(
      padding: EdgeInsets.symmetric(
        horizontal: compact ? 12 : 28,
        vertical: 12,
      ),
      child: Row(
        children: [
          Expanded(
            child: Align(
              alignment: Alignment.centerLeft,
              child: iconOnly
                  ? IconButton(
                      key: backKey,
                      tooltip: backLabel,
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.arrow_back_rounded),
                    )
                  : TextButton.icon(
                      key: backKey,
                      onPressed: () => Navigator.pop(context),
                      icon: const Icon(Icons.arrow_back_rounded, size: 20),
                      label: Text(backLabel),
                    ),
            ),
          ),
          Text(title, style: FocusStyle.navigation),
          Expanded(
            child: Align(
              alignment: Alignment.centerRight,
              child: actions ?? const SizedBox(width: 48, height: 48),
            ),
          ),
        ],
      ),
    );
  }
}
