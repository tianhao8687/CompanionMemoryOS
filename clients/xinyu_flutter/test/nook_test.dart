import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/local_repository.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/nook_scene.dart';
import 'package:xinyu_flutter/ui/nook_sheet.dart';

class NookRepository extends LocalRepository {
  NookRepository({int pixels = 32}) : super('http://127.0.0.1:12345') {
    if (pixels == 48) {
      art['rows'] = List.generate(
        48,
        (y) =>
            y < 12 || y > 39 ? '.' * 48 : '${'.' * 15}0${'1' * 16}0${'.' * 15}',
      );
    }
  }
  bool displayed = true, enabled = true, pinned = false;
  final art = <String, dynamic>{
    'palette': ['#47614C', '#A6C4A0'],
    'rows': List.generate(
      32,
      (y) => y < 8 || y > 25 ? '.' * 32 : '${'.' * 10}0${'1' * 10}0${'.' * 10}',
    ),
  };
  @override
  Future<Map<String, dynamic>> nook({String? at}) async => {
    'items': [
      {
        'id': 'rocket',
        'title': '咖啡小火箭',
        'meaning': '由咖啡小火箭这个比喻想到的一盏灯。',
        'zone': 'desk',
        'slot': 0,
        'art': art,
        'displayed': displayed,
        'pinned': pinned,
        'reality_layer': 'real_world',
        'evidence': [
          {'content': '我是一只靠咖啡续航的小火箭。', 'at': '2026-10-03T10:00:00+00:00'},
        ],
      },
    ],
    'timeline': ['2026-10-03T10:00:00+00:00'],
    'enabled': enabled,
    'daily_limit': 3,
    'busy': false,
    'message': '小窝里多了一件新物品。',
  };
  @override
  Future<Map<String, dynamic>> displayNookObject(String id, bool value) async {
    displayed = value;
    return nook();
  }

  @override
  Future<Map<String, dynamic>> cherishNookObject(String id, bool value) async {
    pinned = value;
    return nook();
  }

  @override
  Future<Map<String, dynamic>> nookSettings(bool value, int limit) async {
    enabled = value;
    return nook();
  }
}

void main() {
  const reviewDir = String.fromEnvironment('NOOK_REVIEW_DIR');
  testWidgets('native pixels beyond 32 stay inside the sprite at both sizes', (
    tester,
  ) async {
    for (final pixels in [32, 48]) {
      final key = GlobalKey();
      final rows = List.filled(pixels, '.' * pixels);
      rows[pixels - 4] = '${'.' * (pixels - 3)}0..';
      await tester.pumpWidget(
        MaterialApp(
          home: Center(
            child: RepaintBoundary(
              key: key,
              child: NookSprite(
                side: 96,
                art: {
                  'palette': ['#DDBB88'],
                  'rows': rows,
                },
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      final boundary =
          key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      await tester.runAsync(() async {
        final image = await boundary.toImage();
        final bytes = (await image.toByteData(
          format: ui.ImageByteFormat.rawRgba,
        ))!.buffer.asUint8List();
        final x = ((pixels - 2.5) * 96 / pixels).floor();
        final y = ((pixels - 3.5) * 96 / pixels).floor();
        expect(image.width, 96);
        expect(bytes.sublist((y * 96 + x) * 4, (y * 96 + x) * 4 + 4), [
          221,
          187,
          136,
          255,
        ]);
        image.dispose();
      });
    }
  });
  setUp(() {
    // The cached loadString Future belongs to the previous test's fake clock.
    // Each test must own its asset-loading callbacks as well as its widgets.
    rootBundle.evict('assets/nook/room.json');
  });
  setUpAll(() async {
    if (reviewDir.isEmpty) return;
    final font = FontLoader('Noto Sans SC')
      ..addFont(rootBundle.load('assets/fonts/NotoSansSC-Variable.ttf'));
    await font.load();
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });
  for (final width in [320.0, 736.0]) {
    testWidgets(
      'pixel nook sources and storage at width $width with large text',
      (tester) async {
        tester.view.physicalSize = Size(width, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final repository = NookRepository(pixels: width == 320 ? 32 : 48);
        final controller = CompanionController(repository: repository)
          ..active = 'conversation';
        final boundaryKey = GlobalKey();
        await tester.pumpWidget(
          RepaintBoundary(
            key: boundaryKey,
            child: MaterialApp(
              theme: ThemeData(fontFamily: 'Noto Sans SC'),
              builder: (context, child) => MediaQuery(
                data: MediaQuery.of(context)
                    .copyWith(textScaler: const TextScaler.linear(1.24)),
                child: child!,
              ),
              home: Scaffold(body: NookSheet(controller: controller)),
            ),
          ),
        );
        await tester.pumpAndSettle();
        // Asset decoding uses real asynchronous work, outside the fake widget clock.
        for (
          var i = 0;
          i < 80 &&
              find.byKey(const ValueKey('nook-canvas')).evaluate().isEmpty;
          i++
        ) {
          await tester.runAsync(
            () => Future<void>.delayed(const Duration(milliseconds: 25)),
          );
          await tester.pumpAndSettle();
        }
        expect(tester.takeException(), isNull);
        expect(find.byType(NookScene), findsOneWidget);
        final canvas = find.byKey(const ValueKey('nook-canvas'));
        expect(canvas, findsOneWidget);
        if (reviewDir.isNotEmpty) {
          final boundary =
              boundaryKey.currentContext!.findRenderObject()!
                  as RenderRepaintBoundary;
          await tester.runAsync(() async {
            final image = await boundary.toImage(pixelRatio: 2);
            final png = await image.toByteData(format: ui.ImageByteFormat.png);
            await Directory(reviewDir).create(recursive: true);
            await File('$reviewDir/nook-widget-${width.toInt()}.png')
                .writeAsBytes(png!.buffer.asUint8List());
            image.dispose();
          });
        }
        await tester.ensureVisible(find.text('桌面'));
        await tester.tap(find.text('桌面'));
        await tester.pumpAndSettle();
        expect(find.text('靠近看看 · 桌面'), findsOneWidget);
        await tester.ensureVisible(canvas);
        final bounds = tester.getRect(canvas);
        await tester.tapAt(
          Offset(
            bounds.left + bounds.width * .25,
            bounds.top + bounds.height * (174 / 420),
          ),
        );
        await tester.pumpAndSettle();
        expect(
          tester
              .widgetList<NookSprite>(find.byType(NookSprite))
              .any((s) => s.side == (width == 320 ? 128 : 192)),
          isTrue,
        );
        await tester.ensureVisible(find.text('看看创作来源'));
        await tester.tap(find.text('看看创作来源'));
        await tester.pumpAndSettle();
        expect(find.text('我是一只靠咖啡续航的小火箭。'), findsOneWidget);
        await tester.ensureVisible(find.text('回到小窝'));
        await tester.tap(find.text('回到小窝'));
        await tester.pumpAndSettle();
        expect(find.text('整个小窝'), findsOneWidget);
        expect(find.text('看看创作来源'), findsNothing);
        await tester.ensureVisible(find.text('咖啡小火箭'));
        await tester.tap(find.text('咖啡小火箭'));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.text('珍藏这一版'));
        await tester.tap(find.text('珍藏这一版'));
        await tester.pumpAndSettle();
        expect(repository.pinned, isTrue);
        expect(find.text('取消珍藏'), findsOneWidget);
        controller.composerText = '原来的草稿';
        expect(controller.composeKeepsakeChat('咖啡小火箭'), isTrue);
        expect(controller.composerText, startsWith('原来的草稿'));
        expect(controller.composerText, contains('咖啡小火箭'));
        await tester.ensureVisible(find.text('收进收纳盒'));
        await tester.tap(find.text('收进收纳盒'));
        await tester.pumpAndSettle();
        expect(repository.displayed, isFalse);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
        controller.dispose();
      },
    );
  }
}
