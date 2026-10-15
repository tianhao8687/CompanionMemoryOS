import 'dart:convert';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'nook_style.dart';

import 'package:flutter/services.dart';

class NookZone {
  NookZone(Map<String, dynamic> data)
    : label = data['label'] as String,
      side = (data['size'] as num).toDouble(),
      view = Rect.fromLTWH(
        (data['view'][0] as num).toDouble(),
        (data['view'][1] as num).toDouble(),
        (data['view'][2] as num).toDouble(),
        (data['view'][2] as num).toDouble(),
      ),
      slots = [
        for (final p in data['slots'] as List)
          Offset((p[0] as num).toDouble(), (p[1] as num).toDouble()),
      ],
      polygon = Path()
        ..addPolygon([
          for (final p in data['polygon'] as List)
            Offset((p[0] as num).toDouble(), (p[1] as num).toDouble()),
        ], true);
  final String label;
  final double side;
  final Rect view;
  final List<Offset> slots;
  final Path polygon;
}

class NookLayout {
  NookLayout(Map<String, dynamic> data)
    : side = (data['side'] as num).toDouble(),
      image = data['image'] as String,
      zones = {
        for (final entry in (data['zones'] as Map).entries)
          entry.key as String: NookZone(
            Map<String, dynamic>.from(entry.value as Map),
          ),
      };
  final double side;
  final String image;
  final Map<String, NookZone> zones;
  Rect get overview => Rect.fromLTWH(0, 0, side, side);
}

Rect nookObjectRect(NookLayout layout, Map<String, dynamic> item) {
  final zone = layout.zones[item['zone']]!;
  final anchor = zone.slots[item['slot'] as int];
  final rows = (item['art']['rows'] as List).cast<String>();
  var left = rows.length, right = 0, bottom = 0;
  for (var y = 0; y < rows.length; y++) {
    for (var x = 0; x < rows[y].length; x++) {
      if (rows[y][x] == '.') continue;
      if (x < left) left = x;
      if (x + 1 > right) right = x + 1;
      bottom = y + 1;
    }
  }
  // Transparent padding never makes a keepsake float above its display surface.
  return Rect.fromLTWH(
    anchor.dx - (left + right) / 2 * zone.side / rows.length,
    anchor.dy - bottom * zone.side / rows.length,
    zone.side,
    zone.side,
  );
}

List<Map<String, dynamic>> _displayed(
  NookLayout layout,
  List<Map<String, dynamic>> items,
) => items.where((o) => o['displayed'] == true).toList()
  ..sort((a, b) {
    final ay = layout.zones[a['zone']]!.slots[a['slot'] as int].dy;
    final by = layout.zones[b['zone']]!.slots[b['slot'] as int].dy;
    final depth = ay.compareTo(by);
    return depth == 0
        ? (a['id'] as String).compareTo(b['id'] as String)
        : depth;
  });

void paintNookSprite(Canvas canvas, Map<String, dynamic> art) {
  final colors = (art['palette'] as List)
      .map(
        (v) => Color(
          int.parse((v as String).substring(1), radix: 16) | 0xff000000,
        ),
      )
      .toList();
  final rows = (art['rows'] as List).cast<String>();
  final paint = Paint()..isAntiAlias = false;
  for (var y = 0; y < rows.length; y++) {
    for (var x = 0; x < rows[y].length; x++) {
      final pixel = rows[y][x];
      if (pixel == '.') continue;
      paint.color = colors[int.parse(pixel, radix: 16)];
      canvas.drawRect(Rect.fromLTWH(x.toDouble(), y.toDouble(), 1, 1), paint);
    }
  }
}

class NookSprite extends StatelessWidget {
  const NookSprite({super.key, required this.art, this.side = 48});
  final Map<String, dynamic> art;
  final double side;
  @override
  Widget build(BuildContext context) => SizedBox.square(
    dimension: side,
    child: CustomPaint(painter: _SpritePainter(art)),
  );
}

class _SpritePainter extends CustomPainter {
  _SpritePainter(this.art);
  final Map<String, dynamic> art;
  @override
  void paint(Canvas canvas, Size size) {
    canvas.save();
    final pixels = (art['rows'] as List).length;
    canvas.scale(size.width / pixels, size.height / pixels);
    paintNookSprite(canvas, art);
    canvas.restore();
  }

  @override
  bool shouldRepaint(_SpritePainter oldDelegate) => oldDelegate.art != art;
}

class NookScene extends StatefulWidget {
  const NookScene({
    super.key,
    required this.items,
    this.selected,
    required this.onSelected,
    this.maxSide = 520,
  });
  final List<Map<String, dynamic>> items;
  final String? selected;
  final ValueChanged<String> onSelected;
  final double maxSide;
  @override
  State<NookScene> createState() => NookSceneState();
}

class NookSceneState extends State<NookScene> {
  NookLayout? _layout;
  ui.Image? _background;
  String _zone = 'all';
  bool _failed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final json = await rootBundle.loadString('assets/nook/room.json');
      final layout = NookLayout(jsonDecode(json) as Map<String, dynamic>);
      final bytes = await rootBundle.load('assets/nook/${layout.image}');
      final codec = await ui.instantiateImageCodec(
        bytes.buffer.asUint8List(bytes.offsetInBytes, bytes.lengthInBytes),
      );
      ui.Image image;
      try {
        image = (await codec.getNextFrame()).image;
      } finally {
        codec.dispose();
      }
      if (!mounted) {
        image.dispose();
        return;
      }
      setState(() {
        _layout = layout;
        _background = image;
        _failed = false;
      });
    } catch (_) {
      if (mounted) setState(() => _failed = true);
    }
  }

  @override
  void didUpdateWidget(NookScene oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.selected == widget.selected) return;
    final item = widget.items
        .where((o) => o['id'] == widget.selected && o['displayed'] == true)
        .firstOrNull;
    if (item != null) _zone = item['zone'] as String;
    if (widget.selected == null) _zone = 'all';
  }

  void showOverview() => setState(() => _zone = 'all');

  @override
  void dispose() {
    _background?.dispose();
    super.dispose();
  }

  void _tap(Offset position, Size size, Rect view) {
    final layout = _layout!;
    final point = Offset(
      view.left + position.dx * view.width / size.width,
      view.top + position.dy * view.height / size.height,
    );
    for (final item in _displayed(layout, widget.items).reversed) {
      final bounds = nookObjectRect(layout, item);
      if (!bounds.contains(point)) continue;
      final rows = (item['art']['rows'] as List).cast<String>();
      final px = ((point.dx - bounds.left) * rows.length / bounds.width)
          .floor();
      final py = ((point.dy - bounds.top) * rows.length / bounds.height)
          .floor();
      if (px >= 0 &&
          px < rows.length &&
          py >= 0 &&
          py < rows.length &&
          rows[py][px] != '.') {
        setState(() => _zone = item['zone'] as String);
        widget.onSelected(item['id'] as String);
        return;
      }
    }
    for (final entry in layout.zones.entries) {
      if (entry.value.polygon.contains(point)) {
        setState(() => _zone = entry.key);
        return;
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final layout = _layout;
    final loaded = layout != null && _background != null;
    final view = loaded
        ? (_zone == 'all' ? layout.overview : layout.zones[_zone]!.view)
        : const Rect.fromLTWH(0, 0, 1000, 1000);
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 440;
        return Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Stack(
              children: [
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Center(
                    child: ConstrainedBox(
                      constraints: BoxConstraints(maxWidth: widget.maxSide),
                      child: Semantics(
                        label: _zone == 'all'
                            ? '整个小窝，点小物件读它的故事'
                            : '靠近看看 · ${layout?.zones[_zone]?.label ?? ''}',
                        image: true,
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(12),
                          child: AspectRatio(
                            aspectRatio: 1,
                            child: !loaded
                                ? ColoredBox(
                                    color: NookStyle.surface,
                                    child: Center(
                                      child: _failed
                                          ? TextButton(
                                              onPressed: () {
                                                setState(() => _failed = false);
                                                _load();
                                              },
                                              child: const Text(
                                                '图片暂时无法读取，点此重试',
                                              ),
                                            )
                                          : const Text(
                                              '正在打开小窝…',
                                              style: TextStyle(
                                                color: NookStyle.muted,
                                              ),
                                            ),
                                    ),
                                  )
                                : TweenAnimationBuilder<Rect?>(
                                    tween: RectTween(
                                      begin: layout.overview,
                                      end: view,
                                    ),
                                    duration:
                                        MediaQuery.disableAnimationsOf(context)
                                        ? Duration.zero
                                        : const Duration(milliseconds: 240),
                                    curve: Curves.easeOutCubic,
                                    builder: (context, camera, child) =>
                                        LayoutBuilder(
                                          builder: (context, constraints) =>
                                              GestureDetector(
                                                key: const ValueKey(
                                                  'nook-canvas',
                                                ),
                                                behavior:
                                                    HitTestBehavior.opaque,
                                                onTapUp: (event) => _tap(
                                                  event.localPosition,
                                                  constraints.biggest,
                                                  camera,
                                                ),
                                                child: CustomPaint(
                                                  painter: NookRoomPainter(
                                                    widget.items,
                                                    widget.selected,
                                                    layout,
                                                    _background!,
                                                    camera!,
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
                ),
              ],
            ),
            const SizedBox(height: 12),
            if (loaded)
              Center(
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      for (final key in [
                        'all',
                        'window',
                        'desk',
                        'shelf',
                        'wall',
                        'floor',
                      ])
                        if (key == 'all' || layout.zones.containsKey(key))
                          Semantics(
                            key: ValueKey('nook-zone-$key'),
                            selected: _zone == key,
                            child: TextButton(
                              onPressed: () => setState(() => _zone = key),
                              style: TextButton.styleFrom(
                                foregroundColor: _zone == key
                                    ? NookStyle.ink
                                    : NookStyle.muted,
                                padding: EdgeInsets.symmetric(
                                  horizontal: compact ? 9 : 14,
                                ),
                                minimumSize: const Size(44, 46),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(6),
                                ),
                              ),
                              child: DecoratedBox(
                                decoration: BoxDecoration(
                                  border: Border(
                                    bottom: BorderSide(
                                      color: _zone == key
                                          ? NookStyle.accent
                                          : Colors.transparent,
                                      width: 2,
                                    ),
                                  ),
                                ),
                                child: Padding(
                                  padding: const EdgeInsets.only(
                                    top: 7,
                                    bottom: 8,
                                  ),
                                  child: Text(
                                    key == 'all'
                                        ? '全景'
                                        : layout.zones[key]!.label,
                                    style: TextStyle(
                                      fontSize: compact ? 12 : 13,
                                      fontWeight: _zone == key
                                          ? FontWeight.w500
                                          : FontWeight.w400,
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                    ],
                  ),
                ),
              ),
          ],
        );
      },
    );
  }
}

class NookRoomPainter extends CustomPainter {
  NookRoomPainter(
    this.items,
    this.selected,
    this.layout,
    this.background,
    this.camera,
  );
  final List<Map<String, dynamic>> items;
  final String? selected;
  final NookLayout layout;
  final ui.Image background;
  final Rect camera;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawColor(NookStyle.surface, BlendMode.src);
    canvas.save();
    canvas.scale(size.width / camera.width, size.height / camera.height);
    canvas.translate(-camera.left, -camera.top);
    canvas.drawImageRect(
      background,
      Rect.fromLTWH(
        0,
        0,
        background.width.toDouble(),
        background.height.toDouble(),
      ),
      layout.overview,
      Paint()..filterQuality = FilterQuality.none,
    );
    for (final item in _displayed(layout, items)) {
      final bounds = nookObjectRect(layout, item);
      final anchor = layout.zones[item['zone']]!.slots[item['slot'] as int];
      if (item['zone'] != 'wall') {
        canvas.drawRect(
          Rect.fromLTWH(
            anchor.dx - bounds.width * .22,
            anchor.dy - 2,
            bounds.width * .44,
            4,
          ),
          Paint()
            ..color = const Color(0x3058483f)
            ..isAntiAlias = false,
        );
      }
      canvas.save();
      canvas.translate(bounds.left, bounds.top);
      canvas.scale(bounds.width / (item['art']['rows'] as List).length);
      paintNookSprite(canvas, Map<String, dynamic>.from(item['art'] as Map));
      canvas.restore();
      if (item['id'] == selected) {
        canvas.drawRect(
          bounds.inflate(3),
          Paint()
            ..color = const Color(0xff78907c)
            ..style = PaintingStyle.stroke
            ..strokeWidth = 2
            ..isAntiAlias = false,
        );
      }
    }
    canvas.restore();
  }

  @override
  bool shouldRepaint(NookRoomPainter oldDelegate) =>
      oldDelegate.items != items ||
      oldDelegate.selected != selected ||
      oldDelegate.camera != camera ||
      oldDelegate.background != background;
}
