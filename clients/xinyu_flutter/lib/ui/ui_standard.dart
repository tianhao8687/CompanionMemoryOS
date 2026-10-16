import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import 'glass.dart';
import 'typography.dart';

/// Mobile list rhythm references Tencent WeUI; desktop uses its own density.
/// Dimensions are logical pixels. Text remains subject to accessibility scaling.
abstract final class XinYuLayout {
  static bool mobile(BuildContext context) =>
      (!kIsWeb &&
          {
            TargetPlatform.android,
            TargetPlatform.iOS,
          }.contains(defaultTargetPlatform)) ||
      MediaQuery.sizeOf(context).width < 600;

  static double inset(BuildContext context) => mobile(context) ? 16 : 24;
  static double rowHeight(BuildContext context) => mobile(context) ? 56 : 52;
  static TextStyle title(BuildContext context) => TextStyle(
    fontFamily: XinYuTypography.family,
    fontSize: mobile(context) ? 18 : 22,
    fontWeight: FontWeight.w500,
    color: XinYuColors.ink,
    height: 1.4,
    letterSpacing: 0,
  );
  static TextStyle body(BuildContext context) => TextStyle(
    fontFamily: XinYuTypography.family,
    fontSize: mobile(context) ? 17 : 16,
    fontWeight: FontWeight.w400,
    color: XinYuColors.ink,
    height: 1.5,
    letterSpacing: 0,
  );
  static const note = TextStyle(
    fontFamily: XinYuTypography.family,
    fontSize: 14,
    fontWeight: FontWeight.w400,
    color: XinYuColors.muted,
    height: 1.5,
    letterSpacing: 0,
  );
  static const section = TextStyle(
    fontFamily: XinYuTypography.family,
    fontSize: 18,
    fontWeight: FontWeight.w500,
    height: 1.4,
    color: XinYuColors.ink,
    letterSpacing: 0,
  );
  static const corners = BorderRadius.all(Radius.circular(12));
  static const line = Color(0xffe4e7ec);
}

Future<T?> showXinYuPage<T>(BuildContext context, WidgetBuilder builder) =>
    XinYuLayout.mobile(context)
    ? Navigator.of(context).push<T>(MaterialPageRoute(builder: builder))
    : showDialog<T>(
        context: context,
        barrierColor: const Color(0x2433403c),
        builder: builder,
      );

/// Android has a full page and a back action. Desktop has a bounded window.
class XinYuPage extends StatelessWidget {
  const XinYuPage({
    super.key,
    required this.title,
    required this.child,
    this.footer,
    this.actions = const [],
    this.onBack,
    this.maxWidth = 760,
    this.canClose = true,
  });
  final String title;
  final Widget child;
  final Widget? footer;
  final List<Widget> actions;
  final VoidCallback? onBack;
  final double maxWidth;
  final bool canClose;

  @override
  Widget build(BuildContext context) {
    final mobile = XinYuLayout.mobile(context);
    final back = canClose ? onBack ?? () => Navigator.pop(context) : null;
    final content = DefaultTextStyle(
      style: XinYuLayout.body(context),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: EdgeInsets.fromLTRB(mobile ? 4 : 16, 8, 8, 8),
            child: Row(
              children: [
                if (mobile || onBack != null)
                  IconButton(
                    tooltip: onBack != null ? '返回设置' : '返回',
                    onPressed: back,
                    icon: const Icon(Icons.arrow_back_rounded),
                  ),
                if (!mobile && onBack == null) const SizedBox(width: 8),
                Expanded(child: Text(title, style: XinYuLayout.title(context))),
                ...actions,
                if (!mobile)
                  IconButton(
                    tooltip: '关闭$title',
                    onPressed: canClose ? () => Navigator.pop(context) : null,
                    icon: const Icon(Icons.close_rounded, size: 22),
                  ),
              ],
            ),
          ),
          const Divider(height: 1, color: XinYuLayout.line),
          Expanded(child: child),
          if (footer != null) ...[
            const Divider(height: 1, color: XinYuLayout.line),
            Padding(
              padding: EdgeInsets.all(XinYuLayout.inset(context)),
              child: footer!,
            ),
          ],
        ],
      ),
    );
    if (mobile) {
      return PopScope(
        canPop: canClose && onBack == null,
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop && canClose) onBack?.call();
        },
        child: Scaffold(
          backgroundColor: XinYuColors.canvas,
          body: Stack(
            children: [
              const Positioned.fill(child: XinYuWallpaper()),
              SafeArea(child: content),
            ],
          ),
        ),
      );
    }
    return Dialog(
      backgroundColor: Colors.transparent,
      elevation: 0,
      insetPadding: const EdgeInsets.symmetric(horizontal: 32, vertical: 24),
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxWidth: maxWidth,
          maxHeight: MediaQuery.sizeOf(context).height * .88,
        ),
        child: GlassSurface(
          grouped: false,
          radius: 20,
          blur: 20,
          tint: XinYuColors.sheet,
          child: Material(type: MaterialType.transparency, child: content),
        ),
      ),
    );
  }
}

class SettingsRow extends StatelessWidget {
  const SettingsRow({
    super.key,
    required this.title,
    required this.onTap,
    this.subtitle,
    this.icon,
    this.selected = false,
  });
  final String title;
  final String? subtitle;
  final IconData? icon;
  final VoidCallback? onTap;
  final bool selected;

  @override
  Widget build(BuildContext context) => Material(
    color: selected ? XinYuColors.selection : Colors.white,
    child: InkWell(
      onTap: onTap,
      child: ConstrainedBox(
        constraints: BoxConstraints(minHeight: XinYuLayout.rowHeight(context)),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
          child: Row(
            children: [
              if (icon != null) ...[
                Icon(icon, size: 22, color: XinYuColors.accent),
                const SizedBox(width: 16),
              ],
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: XinYuLayout.body(context)),
                    if (subtitle != null) ...[
                      const SizedBox(height: 4),
                      Text(subtitle!, style: XinYuLayout.note),
                    ],
                  ],
                ),
              ),
              const SizedBox(width: 8),
              const Icon(
                Icons.chevron_right_rounded,
                size: 20,
                color: XinYuColors.muted,
              ),
            ],
          ),
        ),
      ),
    ),
  );
}
