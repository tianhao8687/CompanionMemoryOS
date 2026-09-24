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
    this.tint = const Color(0x40ffffff),
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
            Color.alphaBlend(const Color(0x20ffffff), tint),
            tint,
            Color.alphaBlend(const Color(0x10ffffff), tint),
          ],
        ),
        border: Border.all(color: const Color(0xb3ffffff), width: 1),
      ),
      child: Padding(padding: padding, child: child),
    );
    return ClipRRect(
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
    );
  }
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
          colors: [Color(0xfff3e8dd), Color(0xffefe4d9), Color(0xffcddde2)],
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
          const Color(0xffcba49a),
          const Color(0xffefc3a5),
          const Color(0xfff8e6cb),
        ],
        180.0,
      ),
      (
        Path()
          ..moveTo(-180, 1010)
          ..cubicTo(120, 470, 340, 1070, 800, 600)
          ..cubicTo(1060, 340, 1230, 680, 1580, 490),
        [
          const Color(0xffb6bcd2),
          const Color(0xffddb5bd),
          const Color(0xffedc7b9),
        ],
        230.0,
      ),
      (
        Path()
          ..moveTo(960, 1220)
          ..cubicTo(1300, 1000, 1320, 840, 1170, 690)
          ..cubicTo(910, 430, 1390, 280, 1600, 350),
        [
          const Color(0xffb4cadc),
          const Color(0xffb8cad4),
          const Color(0xffdce7e7),
        ],
        220.0,
      ),
    ];
    for (final wave in waves) {
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
          ..color = const Color(0x40fff8ef),
      );
    }
    canvas.restore();
    canvas.drawRect(
      rect,
      Paint()
        ..shader = const RadialGradient(
          center: Alignment(-.4, -.65),
          radius: 1.05,
          colors: [Color(0xbffff9ef), Color(0x00fff9ef)],
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
      border: Border.all(color: const Color(0xbfffffff)),
      gradient: const LinearGradient(
        colors: [Color(0xffffecd8), Color(0xffc1d3bc)],
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
