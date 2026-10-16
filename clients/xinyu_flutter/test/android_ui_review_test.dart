import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/demo_repository.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/local_image.dart';
import 'package:xinyu_flutter/ui/message_surface.dart';
import 'package:xinyu_flutter/ui/persona_import_sheet.dart';
import 'package:xinyu_flutter/ui/typography.dart';

import 'settings_navigation.dart';

class SettingsToolRepository extends DemoRepository {
  @override
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text, {
    List<String> imageIds = const [],
    String? quoteId,
  }) async* {
    await for (final event in super.send(
      conversation,
      request,
      text,
      imageIds: imageIds,
      quoteId: quoteId,
    )) {
      if (event['type'] == 'result') {
        final settings = await saveSettings({
          ...(await bootstrap()).settings,
          'font_size': 'large',
        });
        yield {
          ...event,
          'result': <String, dynamic>{
            ...Map<String, dynamic>.from(event['result'] as Map),
            'configuration': {'settings': settings},
            'app_actions': [
              {'page': 'persona_import'},
            ],
          },
        };
      } else {
        yield event;
      }
    }
  }
}

const captureDirectory = String.fromEnvironment('UI_REVIEW_DIR');
Future<void> capture(WidgetTester tester, GlobalKey key, String name) async {
  if (captureDirectory.isEmpty) return;
  await tester.runAsync(() async {
    final render =
        key.currentContext!.findRenderObject() as RenderRepaintBoundary;
    final frame = await render.toImage(pixelRatio: 2);
    final bytes = await frame.toByteData(format: ui.ImageByteFormat.png);
    await Directory(captureDirectory).create(recursive: true);
    await File('$captureDirectory/$name.png')
        .writeAsBytes(bytes!.buffer.asUint8List());
    frame.dispose();
  });
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    if (captureDirectory.isEmpty) return;
    await (FontLoader(
      XinYuTypography.family,
    )..addFont(rootBundle.load(XinYuTypography.fontAsset))).load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });

  testWidgets(
    'a completed AI tool refreshes settings and opens import without a manual settings step',
    (tester) async {
      final c = CompanionController(repository: SettingsToolRepository());
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('message-input')),
        '我想导入人设，字体大一点',
      );
      await tester.pump();
      await tester.tap(find.byKey(const Key('send-message')));
      for (var i = 0; i < 70; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      await tester.pumpAndSettle();
      expect(c.error, isNull);
      expect(c.settings['font_size'], 'large');
      expect(
        c.sending,
        isFalse,
        reason: 'The stream must finish before opening the requested page.',
      );
      expect(
        c.requestedPage.value,
        isNull,
        reason: 'Home must consume the one-time page request.',
      );
      expect(find.byType(PersonaImportSheet), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'cancelling or failing to read a character file preserves the existing persona',
    (tester) async {
      final c = CompanionController();
      addTearDown(c.dispose);
      await c.initialize();
      final original = jsonEncode(c.settings);
      var corrupt = false;
      const channel = MethodChannel('xinyu/local-files');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (call) async {
            expect(call.method, 'pickPersona');
            return corrupt ? Uint8List.fromList(utf8.encode('{broken')) : null;
          });
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(channel, null),
      );
      await tester.pumpWidget(
        MaterialApp(home: PersonaImportSheet(controller: c)),
      );
      await tester.tap(find.byKey(const Key('pick-persona')));
      await tester.pumpAndSettle();
      expect(jsonEncode(c.settings), original);
      corrupt = true;
      await tester.runAsync(() async {
        await tester.tap(find.byKey(const Key('pick-persona')));
        await Future<void>.delayed(const Duration(milliseconds: 300));
      });
      await tester.pumpAndSettle();
      expect(find.textContaining('JSON 格式不完整'), findsOneWidget);
      expect(jsonEncode(c.settings), original);
      await tester.pumpWidget(const SizedBox());
    },
  );

  for (final width in [320.0, 390.0, 600.0]) {
    testWidgets('Android sheet, labels and keyboard fit $width', (
      tester,
    ) async {
      tester.view.physicalSize = Size(width, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      if (width == 320) {
        tester.platformDispatcher.textScaleFactorTestValue = 1.6;
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      }
      final controller = CompanionController();
      addTearDown(controller.dispose);
      final boundary = GlobalKey();
      await tester.pumpWidget(
        RepaintBoundary(
          key: boundary,
          child: XinYuApp(controller: controller),
        ),
      );
      await tester.pumpAndSettle();
      controller.capabilities['focus_features'] = true;
      await tester.tap(find.byKey(const Key('compose-more')));
      await tester.pumpAndSettle();
      expect(find.text('导入人设'), findsOneWidget);
      expect(find.byType(PopupMenuItem<String>), findsNothing);
      expect(tester.takeException(), isNull);
      await capture(tester, boundary, 'actions-${width.toInt()}');
      await tester.tap(find.text('导入人设'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('persona-paste')), findsOneWidget);
      await capture(tester, boundary, 'import-${width.toInt()}');
      await tester.tap(find.byTooltip('返回'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-settings')));
      await tester.pumpAndSettle();
      await settingsSection(tester, '陪伴');
      await capture(tester, boundary, 'settings-${width.toInt()}');
      await settingsGroup(tester, '彼此的称呼');
      final field = find.widgetWithText(TextFormField, '小禾');
      await tester.ensureVisible(field);
      await tester.tap(field);
      tester.view.viewInsets = const FakeViewPadding(bottom: 300);
      addTearDown(tester.view.resetViewInsets);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await capture(tester, boundary, 'keyboard-${width.toInt()}');
      await tester.pumpWidget(const SizedBox());
    });
  }

  testWidgets('paste import saves the existing editable settings', (
    tester,
  ) async {
    final repo = DemoRepository();
    final c = CompanionController(repository: repo);
    addTearDown(c.dispose);
    await c.initialize();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showPersonaImport(context, c),
              child: const Text('导入'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('导入'));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.byKey(const Key('persona-paste')),
      '温柔坦诚，喜欢海边散步。',
    );
    await tester.runAsync(() async {
      await tester.tap(find.text('整理人设'));
      await Future<void>.delayed(const Duration(milliseconds: 300));
    });
    await tester.pumpAndSettle();
    expect(find.text('认识新的 TA'), findsOneWidget);
    await tester.tap(find.text('使用这份人设'));
    await tester.pumpAndSettle();
    expect(c.settings['custom_style'], '温柔坦诚，喜欢海边散步。');
    expect(c.settings['style'], 'custom');
    expect(
      (await repo.bootstrap()).settings['custom_style'],
      c.settings['custom_style'],
    );
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets(
    'scrolling rows do not blur, thumbnails keep their aspect ratio within a decode budget',
    (tester) async {
      final repo = DemoRepository();
      final c = CompanionController(repository: repo);
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      expect(
        find.descendant(
          of: find.byType(MessageSurface),
          matching: find.byType(BackdropFilter),
        ),
        findsNothing,
      );
      final bytes = base64Decode(
        'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGP4z8DwH4QZYAwAR8oH+WdZbrcAAAAASUVORK5CYII=',
      );
      final id = await repo.uploadImage(bytes, 'companion_avatar');
      await tester.pumpWidget(
        MaterialApp(
          home: LocalImage(controller: c, id: id, width: 32, height: 32),
        ),
      );
      await tester.pumpAndSettle();
      final image = tester.widget<Image>(find.byType(Image));
      expect(image.image, isA<ResizeImage>());
      expect((image.image as ResizeImage).policy, ResizeImagePolicy.fit);
      expect((image.image as ResizeImage).width, lessThanOrEqualTo(128));
      await tester.pumpWidget(const SizedBox());
    },
  );
}
