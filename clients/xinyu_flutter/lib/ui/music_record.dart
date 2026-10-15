import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'music_style.dart';

class MusicRecord extends StatefulWidget {
  const MusicRecord({
    super.key,
    required this.size,
    required this.playing,
    this.cover,
  });
  final double size;
  final bool playing;
  final String? cover;
  @override
  State<MusicRecord> createState() => _MusicRecordState();
}

class _MusicRecordState extends State<MusicRecord>
    with SingleTickerProviderStateMixin {
  late final rotation = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 24),
  );
  bool reduced = false;

  void _sync() {
    final animate =
        widget.playing && !reduced && TickerMode.valuesOf(context).enabled;
    if (animate && !rotation.isAnimating) rotation.repeat();
    if (!animate && rotation.isAnimating) rotation.stop(canceled: false);
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    reduced = MediaQuery.disableAnimationsOf(context);
    _sync();
  }

  @override
  void didUpdateWidget(MusicRecord oldWidget) {
    super.didUpdateWidget(oldWidget);
    _sync();
  }

  @override
  void dispose() {
    rotation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Semantics(
    label: widget.playing ? '唱片正在播放' : '唱片已暂停',
    image: true,
    child: SizedBox(
      width: widget.size,
      height: widget.size + 26,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: Colors.black.withValues(alpha: .28),
                    blurRadius: 36,
                    offset: const Offset(0, 22),
                  ),
                ],
              ),
              child: RepaintBoundary(
                child: RotationTransition(
                  key: const Key('music-record-rotation'),
                  turns: rotation,
                  child: SizedBox.square(
                    dimension: widget.size,
                    child: CustomPaint(
                      painter: const _VinylPainter(),
                      child: Center(
                        child: ClipOval(
                          child: SizedBox.square(
                            dimension: widget.size * .59,
                            child: widget.cover == null
                                ? const _RecordLabel()
                                : Image.network(
                                    widget.cover!,
                                    fit: BoxFit.cover,
                                    excludeFromSemantics: true,
                                    errorBuilder: (_, e, st) =>
                                        const _RecordLabel(),
                                  ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
          Positioned(
            top: -4,
            left: widget.size * .64,
            child: TweenAnimationBuilder<double>(
              duration: Duration(milliseconds: reduced ? 0 : 600),
              curve: Curves.easeInOutCubic,
              tween: Tween(end: widget.playing ? 0 : -.38),
              builder: (_, angle, child) => Transform.rotate(
                angle: angle,
                alignment: const Alignment(-.68, -.9),
                child: child,
              ),
              child: CustomPaint(
                size: Size(widget.size * .3, widget.size * .43),
                painter: const _ArmPainter(),
              ),
            ),
          ),
        ],
      ),
    ),
  );
}

class _VinylPainter extends CustomPainter {
  const _VinylPainter();
  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero), radius = size.width / 2;
    canvas.drawCircle(center, radius, Paint()..color = const Color(0xff121818));
    final groove = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = .7;
    for (var i = .63; i < .985; i += .018) {
      canvas.drawCircle(
        center,
        radius * i,
        groove
          ..color = Color.lerp(
            const Color(0xff1b2221),
            const Color(0xff3e4541),
            (i * 42) % 1,
          )!,
      );
    }
    canvas.drawCircle(
      center,
      radius * .99,
      groove..color = const Color(0x33ffffff),
    );
    canvas.drawCircle(
      center,
      radius * .61,
      groove
        ..strokeWidth = 2
        ..color = const Color(0xff090e0e),
    );
    final rect = Rect.fromCircle(center: center, radius: radius);
    final gloss = Paint()
      ..shader = const SweepGradient(
        colors: [
          Colors.transparent,
          Color(0x1fffffff),
          Colors.transparent,
          Color(0x13ffffff),
          Colors.transparent,
        ],
        stops: [0, .15, .3, .65, 1],
        transform: GradientRotation(-math.pi / 2),
      ).createShader(rect);
    canvas.drawCircle(center, radius, gloss);
  }

  @override
  bool shouldRepaint(_VinylPainter oldDelegate) => false;
}

class _ArmPainter extends CustomPainter {
  const _ArmPainter();
  @override
  void paint(Canvas canvas, Size size) {
    final path = Path()
      ..moveTo(size.width * .16, size.height * .05)
      ..lineTo(size.width * .35, size.height * .66)
      ..lineTo(size.width * .7, size.height * .86);
    canvas.drawPath(
      path.shift(const Offset(2, 4)),
      Paint()
        ..color = const Color(0x55000000)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 7
        ..strokeCap = StrokeCap.round,
    );
    canvas.drawPath(
      path,
      Paint()
        ..color = const Color(0xffccd0c9)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 5
        ..strokeCap = StrokeCap.round,
    );
    canvas.drawCircle(
      Offset(size.width * .16, size.height * .05),
      7,
      Paint()..color = MusicStyle.accent,
    );
    canvas.drawLine(
      Offset(size.width * .62, size.height * .81),
      Offset(size.width * .77, size.height * .91),
      Paint()
        ..color = MusicStyle.ink
        ..strokeWidth = 9
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  bool shouldRepaint(_ArmPainter oldDelegate) => false;
}

/// An abstract house label, visibly a fallback rather than an invented album cover.
class _RecordLabel extends StatelessWidget {
  const _RecordLabel();
  @override
  Widget build(BuildContext context) => Semantics(
    label: '暂无专辑封面',
    child: DecoratedBox(
      decoration: BoxDecoration(
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xffc1b28c), Color(0xff50645e), Color(0xff263f44)],
        ),
      ),
      child: Center(
        child: Icon(
          Icons.nightlight_outlined,
          color: Color(0xffece2c9),
          size: 44,
        ),
      ),
    ),
  );
}
