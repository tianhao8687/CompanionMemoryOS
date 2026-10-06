import 'dart:ui' as ui;

import 'package:flutter/material.dart';

double readingScale(Object? size) => switch (size) {
  'large' => 1.12,
  'extra_large' => 1.24,
  _ => 1.0,
};

abstract final class XinYuColors {
  static const ink = Color(0xff172132);
  static const muted = Color(0xff647188);
  static const accent = Color(0xff4a607d);
  static const canvas = Color(0xfff7f6f4);
  static const incoming = Color(0xcfffffff);
  static const outgoing = Color(0xbfdce8f7);
  static const sheet = Color(0xf5f5f6f7);
  static const selection = Color(0x80dce7f6);
  static const peach = Color(0xffe8b99f);
}

abstract final class XinYuShapes {
  static const panelRadius = 32.0;
  static const cardRadius = 28.0;
  static const fieldRadius = 24.0;
  static const panelCorners = BorderRadius.all(Radius.circular(panelRadius));
  static const cardCorners = BorderRadius.all(Radius.circular(cardRadius));
  static const fieldCorners = BorderRadius.all(Radius.circular(fieldRadius));
  static const pillCorners = BorderRadius.all(Radius.circular(999));
  static const panel = RoundedRectangleBorder(borderRadius: panelCorners);
  static const card = RoundedRectangleBorder(borderRadius: cardCorners);
  static const field = RoundedRectangleBorder(borderRadius: fieldCorners);
  static const pill = StadiumBorder();
}

/// Share rounded selection, hover and keyboard-focus surfaces in every menu.
class RoundedChoiceField<T> extends StatelessWidget {
  const RoundedChoiceField({
    super.key,
    required this.initialValue,
    required this.choices,
    required this.onChanged,
    this.label,
  });
  final T initialValue;
  final Map<T, String> choices;
  final ValueChanged<T?>? onChanged;
  final String? label;

  @override
  Widget build(BuildContext context) => DropdownMenuFormField<T>(
    initialSelection: initialValue,
    enabled: onChanged != null,
    onSelected: onChanged,
    selectOnly: true,
    expandedInsets: EdgeInsets.zero,
    menuHeight: 320,
    maxLines: 2,
    label: label == null ? null : Text(label!),
    textStyle: Theme.of(context).textTheme.bodyMedium
        ?.copyWith(fontSize: 13, color: XinYuColors.ink),
    menuStyle: const MenuStyle(
      shape: WidgetStatePropertyAll(XinYuShapes.card),
      padding: WidgetStatePropertyAll(EdgeInsets.all(8)),
    ),
    dropdownMenuEntries: [
      for (final entry in choices.entries)
        DropdownMenuEntry<T>(
          value: entry.key,
          label: entry.value,
          labelWidget: Text(entry.value),
          style: ButtonStyle(
            shape: const WidgetStatePropertyAll(XinYuShapes.pill),
            padding: const WidgetStatePropertyAll(
              EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            ),
            backgroundColor: entry.key == initialValue
                ? const WidgetStatePropertyAll(XinYuColors.selection)
                : null,
          ),
        ),
    ],
  );
}

/// Only non-overlapping surfaces share the inherited BackdropKey. Sheets and
/// drawers establish their own group; no nested blur is added for their fields.
class GlassSurface extends StatelessWidget {
  const GlassSurface({
    super.key,
    required this.child,
    this.radius = XinYuShapes.panelRadius,
    this.padding = EdgeInsets.zero,
    this.tint = const Color(0x28ffffff),
    this.blur = 24,
    this.grouped = true,
    this.outlined = true,
    this.elevated = true,
  });
  final Widget child;
  final double radius, blur;
  final EdgeInsetsGeometry padding;
  final Color tint;
  final bool grouped;
  final bool outlined, elevated;
  @override
  Widget build(BuildContext context) {
    final surface = DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        gradient: tint == Colors.transparent
            ? null
            : LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  Color.alphaBlend(const Color(0x32ffffff), tint),
                  tint,
                  Color.alphaBlend(const Color(0x12e4ecf7), tint),
                ],
                stops: const [0, .48, 1],
              ),
      ),
      child: CustomPaint(
        foregroundPainter: outlined ? _GlassRimPainter(radius) : null,
        child: Padding(padding: padding, child: child),
      ),
    );
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        boxShadow: elevated
            ? const [
                BoxShadow(
                  color: Color(0x08515e70),
                  blurRadius: 24,
                  offset: Offset(0, 8),
                ),
              ]
            : null,
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: blur == 0
            ? surface
            : grouped
            ? BackdropFilter.grouped(
                filter: ui.ImageFilter.blur(sigmaX: blur, sigmaY: blur),
                child: surface,
              )
            : BackdropFilter(
                filter: ui.ImageFilter.blur(sigmaX: blur, sigmaY: blur),
                child: surface,
              ),
      ),
    );
  }
}

/// One translucent rim keeps the edge visible without a raised double outline.
class _GlassRimPainter extends CustomPainter {
  const _GlassRimPainter(this.radius);
  final double radius;
  @override
  void paint(Canvas canvas, Size size) {
    final rect = (Offset.zero & size).deflate(.5);
    final outline = RRect.fromRectAndRadius(rect, Radius.circular(radius));
    canvas.drawRRect(
      outline,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..shader = const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xe6ffffff), Color(0x60ffffff), Color(0xb3ffffff)],
          stops: [0, .55, 1],
        ).createShader(rect),
    );
  }

  @override
  bool shouldRepaint(covariant _GlassRimPainter oldDelegate) =>
      radius != oldDelegate.radius;
}

class XinYuWallpaper extends StatelessWidget {
  const XinYuWallpaper({super.key});
  @override
  Widget build(BuildContext context) => RepaintBoundary(
    child: SizedBox.expand(
      child: CustomPaint(
        painter: _WallpaperPainter(
          compact: MediaQuery.sizeOf(context).width < 880,
        ),
      ),
    ),
  );
}

class _WallpaperPainter extends CustomPainter {
  const _WallpaperPainter({this.compact = false});
  final bool compact;
  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    canvas.drawRect(
      rect,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: compact
              ? const [Color(0xfff8f7f5), Color(0xfff6f6f5), Color(0xffeaf0f7)]
              : const [Color(0xffebf0f5), Color(0xfff3f4f1), Color(0xffe7eef6)],
        ).createShader(rect),
    );
    // Broad, quiet color fields reveal the frosted rims without competing
    // with photos, personal wallpaper or the conversation.
    for (final field in const [
      RadialGradient(
        center: Alignment(-.65, -.9),
        radius: .55,
        colors: [Color(0x809dacb4), Color(0x009dacb4)],
      ),
      RadialGradient(
        center: Alignment(.55, -1.05),
        radius: .5,
        colors: [Color(0x80d6d6ba), Color(0x00d6d6ba)],
      ),
      RadialGradient(
        center: Alignment(.55, .9),
        radius: .7,
        colors: [Color(0x80b9c7bd), Color(0x00b9c7bd)],
      ),
      RadialGradient(
        center: Alignment(-.75, .8),
        radius: .7,
        colors: [Color(0x60b8cfe9), Color(0x00b8cfe9)],
      ),
    ]) {
      canvas.drawRect(
        rect,
        Paint()
          ..color = compact ? const Color(0x38ffffff) : Colors.white
          ..shader = field.createShader(rect),
      );
    }
    canvas.drawRect(
      rect,
      Paint()
        ..shader = const RadialGradient(
          center: Alignment(.05, -.1),
          radius: .85,
          colors: [Color(0xe6fffdf9), Color(0x00fffdf9)],
        ).createShader(rect),
    );
  }

  @override
  bool shouldRepaint(covariant _WallpaperPainter oldDelegate) =>
      compact != oldDelegate.compact;
}

class CompanionAvatar extends StatelessWidget {
  const CompanionAvatar({super.key, this.size = 44, this.label = '禾'});
  final double size;
  final String label;
  @override
  Widget build(BuildContext context) => Container(
    width: size,
    height: size,
    alignment: Alignment.center,
    decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(size * .27),
      border: Border.all(color: const Color(0x80ffffff), width: .7),
      gradient: const LinearGradient(
        colors: [Color(0xffebe9e4), Color(0xffe0e5ec)],
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
      ),
    ),
    child: Text(
      label,
      style: TextStyle(
        color: XinYuColors.ink,
        fontSize: size * .38,
        fontWeight: FontWeight.w500,
      ),
    ),
  );
}
