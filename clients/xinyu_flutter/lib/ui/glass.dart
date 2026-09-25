import 'dart:ui' as ui;

import 'package:flutter/material.dart';

abstract final class XinYuColors {
  static const ink = Color(0xff30463f);
  static const muted = Color(0xff61736c);
  static const accent = Color(0xff406d59);
  static const peach = Color(0xffe8b99f);
}

/// Only non-overlapping surfaces share the inherited BackdropKey. Sheets and
/// drawers establish their own group; no nested blur is added for their fields.
class GlassSurface extends StatelessWidget {
  const GlassSurface({
    super.key,
    required this.child,
    this.radius = 26,
    this.padding = EdgeInsets.zero,
    this.tint = const Color(0x28ffffff),
    this.blur = 24,
    this.grouped = true,
  });
  final Widget child;
  final double radius, blur;
  final EdgeInsetsGeometry padding;
  final Color tint;
  final bool grouped;
  @override
  Widget build(BuildContext context) {
    final surface = DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [
            Color.alphaBlend(const Color(0x52ffffff), tint),
            tint,
            Color.alphaBlend(const Color(0x24ddf9f4), tint),
          ],
          stops: const [0, .48, 1],
        ),
      ),
      child: CustomPaint(
        foregroundPainter: _GlassRimPainter(radius),
        child: Padding(padding: padding, child: child),
      ),
    );
    return DecoratedBox(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        boxShadow: const [
          BoxShadow(
            color: Color(0x12497168),
            blurRadius: 28,
            offset: Offset(0, 12),
          ),
          BoxShadow(
            color: Color(0x28ffffff),
            blurRadius: 2,
            offset: Offset(0, -1),
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: grouped
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

/// A bright upper lip and a faint inner edge give the glass volume without
/// introducing another blur pass or an animation on every chat bubble.
class _GlassRimPainter extends CustomPainter {
  const _GlassRimPainter(this.radius);
  final double radius;
  @override
  void paint(Canvas canvas, Size size) {
    final rect = (Offset.zero & size).deflate(.8);
    final outline = RRect.fromRectAndRadius(rect, Radius.circular(radius));
    canvas.drawRRect(
      outline,
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.5
        ..shader = const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xfaffffff), Color(0x48ffffff), Color(0x99ffffff)],
          stops: [0, .55, 1],
        ).createShader(rect),
    );
    canvas.drawRRect(
      outline.deflate(1.5),
      Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = .7
        ..shader = const LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color(0x48ffffff), Color(0x00436d61), Color(0x16436d61)],
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
  Widget build(BuildContext context) => const RepaintBoundary(
    child: SizedBox.expand(child: CustomPaint(painter: _WallpaperPainter())),
  );
}

class _WallpaperPainter extends CustomPainter {
  const _WallpaperPainter();
  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    canvas.drawRect(
      rect,
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xfffbf4e9), Color(0xffedf1e9), Color(0xffbcdedb)],
        ).createShader(rect),
    );
    canvas.save();
    canvas.scale(size.width / 1400, size.height / 1000);
    final waves = [
      (
        Path()
          ..moveTo(-180, 760)
          ..cubicTo(120, 240, 320, 880, 760, 390)
          ..cubicTo(960, 170, 1260, 370, 1590, 120),
        [
          const Color(0xffd8b6a8),
          const Color(0xfff0c7ac),
          const Color(0xffffebcd),
        ],
        180.0,
      ),
      (
        Path()
          ..moveTo(-180, 1010)
          ..cubicTo(120, 470, 340, 1070, 800, 600)
          ..cubicTo(1060, 340, 1230, 680, 1580, 490),
        [
          const Color(0xffbbc9de),
          const Color(0xffe4c7ce),
          const Color(0xfff1cec1),
        ],
        230.0,
      ),
      (
        Path()
          ..moveTo(960, 1220)
          ..cubicTo(1300, 1000, 1320, 840, 1170, 690)
          ..cubicTo(910, 430, 1390, 280, 1600, 350),
        [
          const Color(0xffa4cec9),
          const Color(0xffb9e0da),
          const Color(0xffe8f5ee),
        ],
        220.0,
      ),
    ];
    for (final wave in waves) {
      canvas.drawPath(
        wave.$1,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = wave.$3 + 22
          ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 24)
          ..shader = LinearGradient(colors: wave.$2)
              .createShader(const Rect.fromLTWH(0, 0, 1400, 1000)),
      );
      canvas.drawPath(
        wave.$1,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = wave.$3
          ..shader = LinearGradient(colors: wave.$2)
              .createShader(const Rect.fromLTWH(0, 0, 1400, 1000)),
      );
      canvas.drawPath(
        wave.$1,
        Paint()
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.2
          ..color = const Color(0x70ffffff),
      );
    }
    canvas.restore();
    canvas.drawRect(
      rect,
      Paint()
        ..shader = const RadialGradient(
          center: Alignment(-.4, -.65),
          radius: 1.05,
          colors: [Color(0xdffffcf5), Color(0x00fff9ef)],
        ).createShader(rect),
    );
  }

  @override
  bool shouldRepaint(covariant _WallpaperPainter oldDelegate) => false;
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
      shape: BoxShape.circle,
      border: Border.all(color: const Color(0xe8ffffff), width: 1.5),
      boxShadow: const [
        BoxShadow(
          color: Color(0x18446e5e),
          blurRadius: 16,
          offset: Offset(0, 6),
        ),
      ],
      gradient: const LinearGradient(
        colors: [Color(0xfffff4e5), Color(0xffc7ddd0), Color(0xffa6c8b5)],
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
