import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/typography.dart';

import '../test/music_test.dart' show ListeningRepository;
import '../test/settings_navigation.dart';

void main() {
  const destination = String.fromEnvironment('UI_REVIEW_DIR');
  setUpAll(() async {
    await (FontLoader(
      XinYuTypography.family,
    )..addFont(rootBundle.load(XinYuTypography.fontAsset))).load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  for (final width in [390.0, 1280.0]) {
    testWidgets(
      'settings, connections and music preview $width',
      (t) async {
        t.view.physicalSize = Size(width, width < 600 ? 844 : 800);
        t.view.devicePixelRatio = 1;
        addTearDown(t.view.resetPhysicalSize);
        addTearDown(t.view.resetDevicePixelRatio);
        final repo = ListeningRepository();
        if (width >= 600) {
          repo.musicState['media'].remove('position_ms');
          repo.musicState['media']['controls']['seek'] = false;
        }
        final c = CompanionController(repository: repo);
        addTearDown(c.dispose);
        final boundary = GlobalKey();
        await t.pumpWidget(
          RepaintBoundary(
            key: boundary,
            child: XinYuApp(controller: c),
          ),
        );
        await t.pumpAndSettle();
        Future<void> capture(String name) async {
          expect(t.takeException(), isNull);
          if (destination.isEmpty) return;
          await t.runAsync(() async {
            final render =
                boundary.currentContext!.findRenderObject()!
                    as RenderRepaintBoundary;
            final frame = await render.toImage(pixelRatio: 1);
            final bytes = await frame.toByteData(
              format: ui.ImageByteFormat.png,
            );
            await Directory(destination).create(recursive: true);
            await File('$destination/$name-${width.toInt()}.png')
                .writeAsBytes(bytes!.buffer.asUint8List());
            frame.dispose();
          });
        }

        await t.tap(find.byKey(const Key('open-settings')));
        await t.pumpAndSettle();
        await capture('settings');
        await settingsSection(t, '连接');
        await capture('connections');
        await closeSettings(t);
        await composeAction(t, 'open-music');
        await t.pump(const Duration(milliseconds: 600));
        c.messages = [
          ChatLine(
            id: 'preview-user',
            text: '这句「晚风把今天轻轻放下」，让我想走慢一点。',
            isUser: true,
            createdAt: DateTime.now().toUtc(),
          ),
          ChatLine(
            id: 'preview-companion',
            text: '像是终于能把一天的事搁下了。今晚这段路，就慢慢走吧。',
            isUser: false,
            createdAt: DateTime.now().toUtc(),
          ),
        ];
        if (width >= 600) c.music.alignLyrics(35000);
        await c.music.act('quiet', silent: false);
        await t.pump(const Duration(milliseconds: 500));
        await t.pump(const Duration(milliseconds: 500));
        await capture('music');
        if (width < 600) {
          await t.tap(find.byKey(const Key('music-lyrics-tab')));
          await t.pump();
          await t.pump(const Duration(milliseconds: 500));
          await t.pump(const Duration(milliseconds: 500));
          await capture('lyrics');
        }
        await c.music.act('pause');
        await t.pump(const Duration(milliseconds: 800));
        await capture('paused');
        await c.music.act('end');
        c.focus.connect(false);
        await t.pumpWidget(const SizedBox());
      },
      variant: TargetPlatformVariant({
        width < 600 ? TargetPlatform.android : TargetPlatform.windows,
      }),
    );
  }
}
