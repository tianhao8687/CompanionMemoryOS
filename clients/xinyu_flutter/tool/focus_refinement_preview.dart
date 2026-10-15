import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/focus_screen.dart';
import 'package:xinyu_flutter/ui/focus_style.dart';
import 'package:xinyu_flutter/ui/typography.dart';

import '../test/focus_presence_test.dart' show PresenceRepository;

class VisualRepository extends PresenceRepository {
  bool showHistory = false;
  @override
  Map<String, dynamic> snapshot() => {
    ...super.snapshot(),
    'history': showHistory
        ? [
            {'intention': '整理桌上的书', 'elapsed_seconds': 1800, 'phase': 'done'},
            {
              'intention': '把要归还的书分开放好，剩下的按平时取用的顺序排列',
              'elapsed_seconds': 480,
              'phase': 'ended',
            },
          ]
        : [],
  };
}

void main() {
  const output = String.fromEnvironment('FOCUS_REVIEW_DIR');
  setUpAll(() async {
    await (FontLoader(
      XinYuTypography.family,
    )..addFont(rootBundle.load(XinYuTypography.fontAsset))).load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  for (final view in [
    (320.0, 1.0),
    (390.0, 1.0),
    (768.0, 1.0),
    (1024.0, 1.0),
    (1440.0, 1.0),
    (320.0, 2.0),
  ]) {
    final (width, scale) = view;
    final suffix = '${width.toInt()}${scale == 1 ? '' : '-2x'}';
    testWidgets('focus, breathing and menus at $suffix', (t) async {
      t.view.physicalSize = Size(width, width < 600 ? 844 : 960);
      t.view.devicePixelRatio = 1;
      addTearDown(t.view.resetPhysicalSize);
      addTearDown(t.view.resetDevicePixelRatio);
      t.platformDispatcher.textScaleFactorTestValue = scale;
      addTearDown(t.platformDispatcher.clearTextScaleFactorTestValue);
      final repo = VisualRepository()..answer = '我就在这里，陪你坐一会儿。';
      final c = CompanionController(repository: repo);
      final boundary = GlobalKey();
      addTearDown(c.dispose);
      await t.pumpWidget(
        RepaintBoundary(
          key: boundary,
          child: XinYuApp(controller: c),
        ),
      );
      await t.pumpAndSettle();
      await t.tap(find.byKey(const Key('open-focus')));
      await t.pumpAndSettle();
      await t.runAsync(
        () => precacheImage(
          const AssetImage(FocusStyle.background),
          t.element(find.byType(FocusScreen)),
        ),
      );
      await t.pumpAndSettle();
      Future<void> tap(Finder finder) async {
        await t.ensureVisible(finder);
        await t.tap(finder);
        await t.pumpAndSettle();
        expect(t.takeException(), isNull);
      }

      Future<void> capture(String name) async {
        expect(t.takeException(), isNull);
        if (output.isEmpty) return;
        await t.runAsync(() async {
          final render =
              boundary.currentContext!.findRenderObject()!
                  as RenderRepaintBoundary;
          final frame = await render.toImage(pixelRatio: 1);
          final bytes = await frame.toByteData(format: ui.ImageByteFormat.png);
          await Directory(output).create(recursive: true);
          await File('$output/$name-$suffix.png')
              .writeAsBytes(bytes!.buffer.asUint8List());
          frame.dispose();
        });
      }

      await capture('setup');
      if (scale > 1) {
        await t.ensureVisible(find.byKey(const Key('focus-start')));
        await t.pumpAndSettle();
        await capture('setup-controls');
      }
      await tap(find.byTooltip('更多专注操作'));
      await capture('menu');
      expect(find.text('提醒设置'), findsOneWidget);
      for (final item in find.byType(MenuItemButton).evaluate()) {
        final rect = t.getRect(find.byWidget(item.widget));
        expect(rect.left, greaterThanOrEqualTo(0));
        expect(rect.right, lessThanOrEqualTo(width));
        expect(
          rect.right,
          greaterThanOrEqualTo(width - (width < 600 ? 32 : 48)),
        );
      }
      await tap(find.text('提醒设置'));
      await capture('reminders');
      await tap(find.text('完成'));
      await tap(find.byTooltip('更多专注操作'));
      await tap(find.text('活动记录').last);
      await capture('records-empty');
      await tap(find.text('关闭'));
      await t.enterText(find.byKey(const Key('focus-task')), '整理桌上的书');
      await tap(find.byKey(const Key('focus-start')));
      await capture('running');
      await tap(find.byKey(const Key('focus-choose-step')));
      await t.enterText(
        find.byKey(const Key('focus-step-input')),
        '先把要留下的书放在一起',
      );
      await t.pumpAndSettle();
      await capture('step-editor');
      await tap(find.text('先不选'));
      await t.ensureVisible(find.byKey(const Key('focus-breathe')));
      await t.tap(find.byKey(const Key('focus-breathe')));
      await t.pump();
      await t.pump(const Duration(milliseconds: 800));
      await capture('breathing-in');
      await t.pump(const Duration(seconds: 5));
      await capture('breathing-out');
      await t.pump(const Duration(seconds: 16));
      await capture('breathing-done');
      if (scale > 1) {
        await t.ensureVisible(find.byKey(const Key('focus-break-return')));
        await t.pumpAndSettle();
        await capture('breathing-controls');
      }
      await tap(find.byKey(const Key('focus-break-return')));
      expect(c.focus.session!.paused, isTrue);
      await tap(find.byKey(const Key('focus-finish')));
      await tap(find.byTooltip('更多专注操作'));
      await capture('menu-ended');
      await tap(find.widgetWithText(MenuItemButton, '留下一点进展'));
      await capture('progress');
      await tap(find.text('先不写'));
      repo.showHistory = true;
      await tap(find.byTooltip('更多专注操作'));
      await tap(find.widgetWithText(MenuItemButton, '活动记录'));
      await capture('records');
      await tap(find.text('关闭'));
      c.focus.connect(false);
      await t.pumpWidget(const SizedBox.shrink());
    });
  }
}
