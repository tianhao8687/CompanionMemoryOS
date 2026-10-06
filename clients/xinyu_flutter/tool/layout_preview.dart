// Isolated visual review. This entry point uses synthetic DemoRepository data.
// flutter test tool/layout_preview.dart --dart-define=XINYU_PREVIEW_DIR=<absolute path>
// Uses the same bundled font as the application on both platforms.
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/demo_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/chat.dart';
import 'package:xinyu_flutter/ui/glass.dart';
import 'package:xinyu_flutter/ui/typography.dart';

class _PreviewRepository extends DemoRepository {
  _PreviewRepository({this.avatar, this.flowers});
  final Uint8List? avatar, flowers;
  final time = DateTime(
    DateTime.now().year,
    DateTime.now().month,
    DateTime.now().day,
    18,
    35,
  );
  @override
  Future<Snapshot> bootstrap() async {
    final original = await super.bootstrap();
    return Snapshot(
      {
        ...original.settings,
        if (avatar != null) 'companion_avatar': 'preview-avatar',
      },
      [
        Conversation(
          'flowers',
          '窗边的小雏菊',
          updatedAt: time.add(const Duration(minutes: 7)),
        ),
        Conversation(
          'walk',
          '周末的散步',
          updatedAt: time.subtract(const Duration(days: 1)),
        ),
        Conversation(
          'night',
          '睡前聊一会儿',
          updatedAt: time.subtract(const Duration(days: 2)),
        ),
      ],
      capabilities: original.capabilities,
    );
  }

  @override
  Future<Uint8List> image(String id) async => switch (id) {
    'preview-avatar' when avatar != null => avatar!,
    'preview-flowers' when flowers != null => flowers!,
    _ => await super.image(id),
  };

  @override
  Future<MessagePage> messages(String conversation, {int? before}) async =>
      MessagePage([
        ChatLine(
          id: 'p1',
          text: '今天给自己买了花。',
          isUser: true,
          imageIds: flowers == null ? const [] : const ['preview-flowers'],
          sequence: 1,
          createdAt: time,
        ),
        ChatLine(
          id: 'p2',
          text: '是你喜欢的小雏菊。\n\n这次准备放在窗边吗？',
          isUser: false,
          sequence: 2,
          createdAt: time.add(const Duration(minutes: 1)),
        ),
        ChatLine(
          id: 'p3',
          text: '嗯，那里下午有阳光。',
          isUser: true,
          sequence: 3,
          createdAt: time.add(const Duration(minutes: 2)),
        ),
        ChatLine(
          id: 'p4',
          text: '等你摆好了，拍给我看看。\n\n想看看你的小小角落。',
          isUser: false,
          sequence: 4,
          createdAt: time.add(const Duration(minutes: 3)),
        ),
      ]);
}

void main() {
  const destination = String.fromEnvironment('XINYU_PREVIEW_DIR');
  const assetDirectory = String.fromEnvironment('XINYU_PREVIEW_ASSETS');
  Uint8List? avatar, flowers;
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    if (assetDirectory.isNotEmpty) {
      avatar = await File('$assetDirectory/avatar.png').readAsBytes();
      flowers = await File('$assetDirectory/flowers.png').readAsBytes();
    }
    final font = FontLoader(XinYuTypography.family)
      ..addFont(rootBundle.load(XinYuTypography.fontAsset));
    await font.load();
    final icons = FontLoader('MaterialIcons')
      ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
    await icons.load();
  });

  for (final layout in [
    ('android', const Size(390, 844), TargetPlatform.android),
    ('windows', const Size(1586, 992), TargetPlatform.windows),
  ]) {
    testWidgets('render ${layout.$1} with synthetic conversation', (
      tester,
    ) async {
      if (destination.isEmpty) {
        fail('Set XINYU_PREVIEW_DIR to an isolated output directory.');
      }
      final previousShadows = debugDisableShadows;
      debugDisableShadows = false;
      tester.view.physicalSize = layout.$2;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final c = CompanionController(
        repository: _PreviewRepository(avatar: avatar, flowers: flowers),
      );
      addTearDown(c.dispose);
      final boundaryKey = GlobalKey();
      await tester.pumpWidget(
        RepaintBoundary(
          key: boundaryKey,
          child: XinYuApp(controller: c),
        ),
      );
      await tester.pumpAndSettle();
      expect(c.messages, hasLength(4));
      // Complete asset and photo decoding before exporting the widgets.
      await tester.runAsync(() async {
        await precacheImage(
          const AssetImage('assets/branding/xinyu-logo.png'),
          boundaryKey.currentContext!,
        );
        if (avatar != null) {
          await precacheImage(
            MemoryImage(avatar!),
            boundaryKey.currentContext!,
          );
        }
        if (flowers != null) {
          await precacheImage(
            MemoryImage(flowers!),
            boundaryKey.currentContext!,
          );
        }
      });
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      Future<void> capture(String name) async {
        final boundary =
            boundaryKey.currentContext!.findRenderObject()!
                as RenderRepaintBoundary;
        await tester.runAsync(() async {
          final frame = await boundary.toImage(pixelRatio: 2);
          final png = await frame.toByteData(format: ui.ImageByteFormat.png);
          await Directory(destination).create(recursive: true);
          await File('$destination/$name.png')
              .writeAsBytes(png!.buffer.asUint8List());
          frame.dispose();
        });
      }

      await capture(layout.$1);
      if (layout.$1 == 'android') {
        await tester.tap(find.byTooltip('打开对话列表'));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await capture('android-navigation');
        await tester.tap(find.byTooltip('收起对话列表'));
        await tester.pumpAndSettle();
      }
      if (layout.$1 == 'windows') {
        await tester.tap(find.byKey(const Key('edit-companion-remark')));
        await tester.pumpAndSettle();
        await tester.enterText(find.byKey(const Key('companion-remark')), '月亮');
        await tester.enterText(
          find.byKey(const Key('companion-note')),
          '留给自己的小小备注。',
        );
        await tester.pumpAndSettle();
        await capture('windows-remark');
        await tester.tap(find.byTooltip('取消备注'));
        await tester.pumpAndSettle();
      }
      await tester.tap(find.byKey(const Key('open-settings')));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await capture('${layout.$1}-settings');
      await tester.tap(find.byTooltip('关闭设置'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-character-home')));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await capture('${layout.$1}-profile');
      await tester.pumpWidget(const SizedBox());
      debugDisableShadows = previousShadows;
    }, variant: TargetPlatformVariant.only(layout.$3));
  }

  testWidgets('render message component sheet', (tester) async {
    if (destination.isEmpty) {
      fail('Set XINYU_PREVIEW_DIR to an isolated output directory.');
    }
    final previousShadows = debugDisableShadows;
    debugDisableShadows = false;
    tester.view.physicalSize = const Size(1040, 540);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final controller = CompanionController();
    addTearDown(controller.dispose);
    await controller.initialize();
    final boundaryKey = GlobalKey();
    await tester.pumpWidget(
      RepaintBoundary(
        key: boundaryKey,
        child: _MessageComponentSheet(controller: controller),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final boundary =
        boundaryKey.currentContext!.findRenderObject()!
            as RenderRepaintBoundary;
    await tester.runAsync(() async {
      final frame = await boundary.toImage(pixelRatio: 2);
      final png = await frame.toByteData(format: ui.ImageByteFormat.png);
      await Directory(destination).create(recursive: true);
      await File('$destination/message-components.png')
          .writeAsBytes(png!.buffer.asUint8List());
      frame.dispose();
    });
    await tester.pumpWidget(const SizedBox());
    debugDisableShadows = previousShadows;
  });
}

/// Uses the production message widget; labels belong only to this review sheet.
class _MessageComponentSheet extends StatelessWidget {
  const _MessageComponentSheet({required this.controller});
  final CompanionController controller;

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    theme: ThemeData(
      useMaterial3: true,
      fontFamily: XinYuTypography.family,
      textTheme: XinYuTypography.textTheme,
      colorScheme: ColorScheme.fromSeed(seedColor: XinYuColors.accent)
          .copyWith(onSurface: XinYuColors.ink),
    ),
    home: Material(
      child: Stack(
        children: [
          const Positioned.fill(child: XinYuWallpaper()),
          Padding(
            padding: const EdgeInsets.all(32),
            child: BackdropGroup(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Text(
                    '消息气泡',
                    style: TextStyle(fontSize: 24, fontWeight: FontWeight.w500),
                  ),
                  const SizedBox(height: 32),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(child: _column(false)),
                      const SizedBox(width: 48),
                      Expanded(child: _column(true)),
                    ],
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    ),
  );

  Widget _column(bool isUser) => Column(
    crossAxisAlignment: isUser
        ? CrossAxisAlignment.end
        : CrossAxisAlignment.start,
    children: [
      Text(
        isUser ? '你的消息' : '对方的消息',
        style: const TextStyle(fontSize: 14, color: XinYuColors.muted),
      ),
      const SizedBox(height: 8),
      for (var index = 0; index < 3; index++)
        MessageBubble(
          controller: controller,
          name: controller.companionDisplayName,
          interactive: false,
          line: ChatLine(
            id: 'component-$isUser-$index',
            isUser: isUser,
            text: index == 0
                ? (isUser ? '今天给自己买了花。' : '是你喜欢的小雏菊。')
                : index == 1
                ? (isUser
                      ? '嗯，那里下午有阳光。\n今晚想慢下来，好好听一张专辑。'
                      : '等你摆好了，拍给我看看。\n想看看你的小小角落。')
                : (isUser ? '就放在这里吧。' : '那就把这个位置留给它。'),
            quote: index == 2
                ? QuotedMessage('quoted-synthetic', '窗边下午有阳光。', !isUser)
                : null,
          ),
        ),
    ],
  );
}
