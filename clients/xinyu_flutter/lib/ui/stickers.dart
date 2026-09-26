import 'dart:math' as math;
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../data/image_import.dart';
import '../data/models.dart';
import '../state/companion_controller.dart';
import 'glass.dart';

class StickerView extends StatelessWidget {
  const StickerView({
    super.key,
    required this.item,
    required this.controller,
    this.size = 132,
  });
  final StickerItem item;
  final CompanionController controller;
  final double size;
  @override
  Widget build(BuildContext context) => Semantics(
    label: '表情包：${item.label}',
    image: true,
    child: SizedBox(
      width: size,
      height: size,
      child: item.kind == 'builtin'
          ? CustomPaint(
              painter: _DropletPainter(
                item.id,
                item.label,
                Theme.of(context).textTheme.bodyMedium?.fontFamily,
              ),
            )
          : item.kind == 'missing'
          ? const Center(child: Text('表情包已删除', style: TextStyle(fontSize: 11)))
          : FutureBuilder<Uint8List>(
              future: controller.stickerImage(item.id),
              builder: (_, value) => value.hasData
                  ? Image.memory(
                      value.data!,
                      fit: BoxFit.contain,
                      gaplessPlayback: true,
                      errorBuilder: (_, error, stack) =>
                          const Center(child: Text('表情包不可用')),
                    )
                  : Center(
                      child: Text(
                        value.hasError ? '表情包不可用' : '加载中…',
                        style: const TextStyle(fontSize: 11),
                      ),
                    ),
            ),
    ),
  );
}

/// Original vector artwork. All expressions share one soft, translucent character.
class _DropletPainter extends CustomPainter {
  _DropletPainter(this.id, this.label, this.fontFamily);
  final String id, label;
  final String? fontFamily;
  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    canvas.scale(size.width / 132, size.height / 132);
    final ink = Paint()
      ..color = const Color(0xff38584c)
      ..strokeWidth = 2.6
      ..strokeCap = StrokeCap.round
      ..style = PaintingStyle.stroke;
    final face = Path()
      ..moveTo(25, 69)
      ..cubicTo(20, 36, 47, 19, 63, 23)
      ..cubicTo(78, 13, 110, 38, 108, 68)
      ..cubicTo(106, 98, 91, 102, 65, 102)
      ..cubicTo(39, 102, 25, 93, 25, 69)
      ..close();
    canvas.drawOval(
      const Rect.fromLTWH(34, 96, 67, 8),
      Paint()..color = const Color(0x1596ad9e),
    );
    canvas.drawPath(
      face,
      Paint()
        ..shader = const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xfff6fff8), Color(0xffb8ddcb), Color(0xff91c1b0)],
        ).createShader(const Rect.fromLTWH(23, 20, 88, 82)),
    );
    canvas.drawPath(
      face,
      Paint()
        ..color = const Color(0xff7eaa95)
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1.3,
    );
    canvas.drawOval(
      const Rect.fromLTWH(36, 30, 29, 11),
      Paint()..color = const Color(0xb0ffffff),
    );
    for (final x in [42.0, 86.0]) {
      canvas.drawOval(
        Rect.fromCenter(center: Offset(x, 76), width: 16, height: 8),
        Paint()..color = const Color(0x85f0a995),
      );
    }
    final sleepy = id == 'builtin_sleepy';
    final happy = [
      'builtin_happy',
      'builtin_hug',
      'builtin_cheer',
    ].contains(id);
    for (final x in [49.0, 82.0]) {
      if (sleepy || happy) {
        final eye = Path()
          ..moveTo(x - 5, 64)
          ..quadraticBezierTo(x, happy ? 55 : 70, x + 5, 64);
        canvas.drawPath(eye, ink);
      } else {
        canvas.drawOval(
          Rect.fromCenter(
            center: Offset(x, 63),
            width: 4,
            height: id == 'builtin_surprise' ? 9 : 6,
          ),
          Paint()..color = ink.color,
        );
      }
    }
    if (id == 'builtin_surprise') {
      canvas.drawOval(const Rect.fromLTWH(61, 74, 10, 14), ink);
    } else if (id == 'builtin_sad') {
      canvas.drawPath(
        Path()
          ..moveTo(59, 83)
          ..quadraticBezierTo(66, 76, 73, 83),
        ink,
      );
      canvas.drawOval(
        const Rect.fromLTWH(44, 71, 5, 10),
        Paint()..color = const Color(0xff75bbd8),
      );
    } else {
      canvas.drawPath(
        Path()
          ..moveTo(59, 76)
          ..quadraticBezierTo(66, 87, 73, 76),
        ink,
      );
    }
    final hug = id == 'builtin_hug';
    final shy = id == 'builtin_shy';
    canvas.drawPath(
      Path()
        ..moveTo(30, 80)
        ..quadraticBezierTo(
          hug ? 6 : 38,
          hug ? 59 : 98,
          shy
              ? 57
              : hug
              ? 9
              : 46,
          shy
              ? 81
              : hug
              ? 67
              : 85,
        ),
      ink,
    );
    canvas.drawPath(
      Path()
        ..moveTo(101, 80)
        ..quadraticBezierTo(
          hug ? 126 : 95,
          hug ? 59 : 98,
          shy
              ? 75
              : hug
              ? 123
              : 86,
          shy
              ? 81
              : hug
              ? 67
              : 85,
        ),
      ink,
    );
    if (id == 'builtin_miss_you' || shy || hug) {
      _heart(canvas, const Offset(108, 24), 11);
      if (id == 'builtin_miss_you') _heart(canvas, const Offset(22, 42), 7);
    } else if (sleepy) {
      final tp = TextPainter(
        text: TextSpan(
          text: 'z Z',
          style: TextStyle(
            fontFamily: fontFamily,
            fontSize: 17,
            fontWeight: FontWeight.bold,
            color: Color(0xff7c9bca),
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      tp.paint(canvas, const Offset(93, 18));
    } else {
      for (final p in [const Offset(18, 43), const Offset(113, 35)]) {
        final star = Path();
        for (var i = 0; i < 8; i++) {
          final r = i.isEven ? 8.0 : 2.8;
          final point = Offset(
            p.dx + math.cos(i * math.pi / 4) * r,
            p.dy + math.sin(i * math.pi / 4) * r,
          );
          if (i == 0) {
            star.moveTo(point.dx, point.dy);
          } else {
            star.lineTo(point.dx, point.dy);
          }
        }
        star.close();
        canvas.drawPath(star, Paint()..color = const Color(0xffe4b868));
      }
    }
    final caption = TextPainter(
      text: TextSpan(
        text: label,
        style: TextStyle(
          fontFamily: fontFamily,
          fontSize: 15,
          fontWeight: FontWeight.w700,
          color: Color(0xff527763),
          letterSpacing: 2,
        ),
      ),
      textDirection: TextDirection.ltr,
    )..layout(maxWidth: 128);
    caption.paint(canvas, Offset((132 - caption.width) / 2, 109));
    canvas.restore();
  }

  void _heart(Canvas c, Offset p, double r) {
    c.drawPath(
      Path()
        ..moveTo(p.dx, p.dy + r)
        ..cubicTo(p.dx - r * 2, p.dy, p.dx - r, p.dy - r, p.dx, p.dy - r / 3)
        ..cubicTo(p.dx + r, p.dy - r, p.dx + r * 2, p.dy, p.dx, p.dy + r),
      Paint()..color = const Color(0xffe9a79c),
    );
  }

  @override
  bool shouldRepaint(covariant _DropletPainter old) =>
      old.id != id || old.label != label || old.fontFamily != fontFamily;
}

Future<void> showStickerLibrary(
  BuildContext context,
  CompanionController controller,
) => showDialog<void>(
  context: context,
  builder: (_) => _StickerLibrary(controller),
);

class _StickerLibrary extends StatefulWidget {
  const _StickerLibrary(this.controller);
  final CompanionController controller;
  @override
  State<_StickerLibrary> createState() => _StickerLibraryState();
}

class _StickerLibraryState extends State<_StickerLibrary> {
  List<StickerItem> items = [];
  bool loading = true;
  String? error;
  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = await widget.controller.localConnection!.stickers();
      if (mounted) setState(() => items = list);
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '表情包暂时无法读取'),
        );
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _import() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final bytes = await pickLocalSticker();
      if (bytes == null || !mounted) return;
      final field = TextEditingController();
      final label = await showDialog<String>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('给表情写个含义'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Image.memory(bytes, width: 120, height: 120, fit: BoxFit.contain),
              const SizedBox(height: 12),
              TextField(
                controller: field,
                maxLength: 32,
                autofocus: true,
                decoration: const InputDecoration(hintText: '例如：抱抱、开心地转圈'),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () {
                if (field.text.trim().isNotEmpty) {
                  Navigator.pop(context, field.text.trim());
                }
              },
              child: const Text('导入'),
            ),
          ],
        ),
      );
      // The closing route may still build during its animation.
      Future<void>.delayed(const Duration(seconds: 1), field.dispose);
      if (label != null) {
        await widget.controller.localConnection!.uploadSticker(bytes, label);
        await _load();
      }
    } catch (e) {
      if (mounted) {
        setState(
          () => error = widget.controller.reportFailure(e, title: '表情包未能导入'),
        );
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => Dialog(
    backgroundColor: Colors.transparent,
    child: ConstrainedBox(
      constraints: const BoxConstraints(maxWidth: 560, maxHeight: 640),
      child: GlassSurface(
        radius: XinYuShapes.panelRadius,
        tint: const Color(0xebf4faf5),
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                const Expanded(
                  child: Text(
                    '我们的表情包',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
                  ),
                ),
                IconButton(
                  tooltip: '关闭表情库',
                  onPressed: () => Navigator.pop(context),
                  icon: const Icon(Icons.close),
                ),
              ],
            ),
            const Text(
              'AI 会按语境选用；导入时写清表情含义。图片只存在本机。',
              style: TextStyle(color: XinYuColors.muted, height: 1.5),
            ),
            if (error != null)
              Text(error!, style: const TextStyle(color: Color(0xffa35b4a))),
            if (loading) const LinearProgressIndicator(),
            const SizedBox(height: 12),
            Flexible(
              child: GridView.builder(
                shrinkWrap: true,
                gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                  maxCrossAxisExtent: 164,
                  childAspectRatio: .78,
                  crossAxisSpacing: 8,
                  mainAxisSpacing: 8,
                ),
                itemCount: items.length,
                itemBuilder: (_, i) {
                  final item = items[i];
                  return Column(
                    children: [
                      Expanded(
                        child: FittedBox(
                          child: StickerView(
                            item: item,
                            controller: widget.controller,
                          ),
                        ),
                      ),
                      Text(
                        item.kind == 'builtin' ? '内置' : item.label,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(fontSize: 11),
                      ),
                      if (item.kind == 'custom')
                        TextButton(
                          onPressed: loading
                              ? null
                              : () async {
                                  setState(() => loading = true);
                                  try {
                                    await widget.controller.deleteSticker(
                                      item.id,
                                    );
                                    await _load();
                                  } catch (e) {
                                    if (mounted) {
                                      setState(() {
                                        error = widget.controller.reportFailure(
                                          e,
                                          title: '表情包未删除',
                                        );
                                        loading = false;
                                      });
                                    }
                                  }
                                },
                          child: const Text(
                            '删除',
                            style: TextStyle(fontSize: 11),
                          ),
                        ),
                    ],
                  );
                },
              ),
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: loading ? null : _import,
              icon: const Icon(Icons.add_photo_alternate_outlined),
              label: const Text('导入图片 / GIF'),
            ),
            const SizedBox(height: 8),
            const Text(
              '最多 24 张 · 每张 2 MB · GIF ≤ 512 像素、60 帧',
              style: TextStyle(fontSize: 10, color: XinYuColors.muted),
            ),
          ],
        ),
      ),
    ),
  );
}
