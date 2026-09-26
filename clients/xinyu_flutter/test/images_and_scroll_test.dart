import 'dart:convert';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/image_import.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

final pixel = base64Decode(
  'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGP4z8DwH4QZYAwAR8oH+WdZbrcAAAAASUVORK5CYII=',
);

Future<void> finishReply(WidgetTester tester) async {
  for (var i = 0; i < 60; i++) {
    await tester.pump(const Duration(milliseconds: 40));
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(const MethodChannel('xinyu/local-files'), (
          call,
        ) async {
          expect(call.method, 'pickImage');
          return pixel;
        }),
  );
  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          const MethodChannel('xinyu/local-files'),
          null,
        ),
  );

  testWidgets(
    'Outgoing messages go to bottom from old history; manual reading stays put',
    (tester) async {
      final controller = CompanionController();
      addTearDown(controller.dispose);
      await tester.pumpWidget(XinYuApp(controller: controller));
      await tester.pumpAndSettle();
      await controller.benchmark();
      await tester.pumpAndSettle();
      final scroll = tester
          .widget<ListView>(find.byKey(const Key('chat-list')))
          .controller!;
      scroll.jumpTo(1200);
      await tester.pumpAndSettle();
      expect(scroll.offset, greaterThan(100));
      await tester.enterText(find.byKey(const Key('message-input')), '从旧消息处发送');
      await tester.pump();
      await tester.tap(find.byKey(const Key('send-message')));
      await tester.pump();
      await tester.pump();
      expect(scroll.offset, 0);
      // Streaming updates must not drag the user back after they deliberately scroll away.
      await tester.drag(
        find.byKey(const Key('chat-list')),
        const Offset(0, 700),
      );
      await tester.pump();
      await finishReply(tester);
      expect(scroll.offset, greaterThan(100));
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'Image-only send retains the photo and scrolls to latest on narrow phones',
    (tester) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final controller = CompanionController();
      addTearDown(controller.dispose);
      await tester.pumpWidget(XinYuApp(controller: controller));
      await tester.pumpAndSettle();
      await controller.benchmark();
      await tester.pumpAndSettle();
      await tester.runAsync(controller.attachImage);
      await tester.pumpAndSettle();
      expect(controller.error, isNull);
      final id = controller.pendingImages.single;
      final scroll = tester
          .widget<ListView>(find.byKey(const Key('chat-list')))
          .controller!;
      scroll.jumpTo(1200);
      await tester.pumpAndSettle();
      await tester.pump();
      await tester.tap(find.byKey(const Key('send-message')));
      await tester.pump();
      await tester.pump();
      await tester.pump();
      expect(scroll.offset, 0);
      await finishReply(tester);
      expect(controller.pendingImages, isEmpty);
      expect(
        controller.messages.where((m) => m.imageIds.contains(id)),
        hasLength(1),
      );
      expect(controller.messages.last.text, contains('示例回复'));
      expect(scroll.offset, 0);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'Image choices preserve unsaved profile; save applies and cancel discards',
    (tester) async {
      final controller = CompanionController();
      addTearDown(controller.dispose);
      await tester.pumpWidget(XinYuApp(controller: controller));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-settings')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextFormField, '怎么称呼 TA'),
        '阿棠',
      );
      final settingsScroll = find
          .descendant(
            of: find.byKey(const Key('settings-scroll')),
            matching: find.byType(Scrollable),
          )
          .first;
      await tester.scrollUntilVisible(
        find.byKey(const Key('user-profile')),
        250,
        scrollable: settingsScroll,
      );
      await tester.enterText(find.byKey(const Key('user-profile')), '海边的画家');
      await tester.tap(find.text('外观'));
      await tester.pumpAndSettle();
      for (final field in [
        'background_image',
        'user_avatar',
        'companion_avatar',
      ]) {
        final picker = find.byKey(Key('pick-$field'));
        await tester.scrollUntilVisible(
          picker,
          220,
          scrollable: settingsScroll,
        );
        await tester.runAsync(() async {
          await tester.tap(picker);
          for (var i = 0; i < 100 && controller.loading; i++) {
            await Future<void>.delayed(const Duration(milliseconds: 20));
          }
          await Future<void>.delayed(const Duration(milliseconds: 20));
        });
        await tester.pumpAndSettle();
      }
      await tester.tap(find.text('保存设置'));
      await tester.pumpAndSettle();
      expect(controller.companionName, '阿棠');
      expect(controller.settings['user_persona'], '海边的画家');
      for (final field in [
        'background_image',
        'user_avatar',
        'companion_avatar',
      ]) {
        expect(controller.settings[field], isNotNull);
      }
      final saved = controller.settings['background_image'];
      await tester.tap(find.byKey(const Key('open-settings')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('外观'));
      await tester.pumpAndSettle();
      final picker = find.byKey(const Key('pick-background_image'));
      await tester.scrollUntilVisible(picker, 220, scrollable: settingsScroll);
      await tester.runAsync(() async {
        await tester.tap(picker);
        for (var i = 0; i < 100 && controller.loading; i++) {
          await Future<void>.delayed(const Duration(milliseconds: 20));
        }
        await Future<void>.delayed(const Duration(milliseconds: 20));
      });
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('关闭设置'));
      await tester.pumpAndSettle();
      expect(controller.settings['background_image'], saved);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  test(
    'Image normalization bounds dimensions and rejects invalid data',
    () async {
      final recorder = ui.PictureRecorder();
      final canvas = Canvas(recorder);
      canvas.drawRect(
        const Rect.fromLTWH(0, 0, 3000, 1500),
        Paint()..color = Colors.teal,
      );
      final picture = recorder.endRecording();
      final source = await picture.toImage(3000, 1500);
      final bytes = (await source.toByteData(format: ui.ImageByteFormat.png))!
          .buffer
          .asUint8List();
      final resized = await normalizeImage(bytes, maxSide: 512);
      final codec = await ui.instantiateImageCodec(resized);
      final frame = await codec.getNextFrame();
      expect(frame.image.width, 512);
      expect(frame.image.height, 256);
      frame.image.dispose();
      codec.dispose();
      source.dispose();
      picture.dispose();
      await expectLater(
        normalizeImage(Uint8List.fromList([1, 2, 3])),
        throwsException,
      );
    },
  );
}
