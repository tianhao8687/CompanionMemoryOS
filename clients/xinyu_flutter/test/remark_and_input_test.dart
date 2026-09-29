import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/demo_repository.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

void viewport(WidgetTester tester, Size size) {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
}

Future<void> finishReply(WidgetTester tester) async {
  for (var i = 0; i < 100; i++) {
    await tester.pump(const Duration(milliseconds: 40));
  }
}

void main() {
  testWidgets(
    'private remark saves, reloads, cancels and clears independently of role',
    (tester) async {
      viewport(tester, const Size(1280, 840));
      final repository = DemoRepository();
      final c = CompanionController(repository: repository);
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('edit-companion-remark')));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('companion-remark')),
        '  月亮  ',
      );
      await tester.enterText(
        find.byKey(const Key('companion-note')),
        '  我的私人备注  ',
      );
      await tester.tap(find.byKey(const Key('save-remark')));
      await tester.pumpAndSettle();
      expect(c.companionName, '小禾');
      expect(c.companionDisplayName, '月亮');
      expect(c.settings['companion_note'], '我的私人备注');
      expect(find.text('月亮'), findsWidgets);
      await tester.pumpWidget(const SizedBox());
      final reloaded = CompanionController(repository: repository);
      addTearDown(reloaded.dispose);
      await tester.pumpWidget(XinYuApp(controller: reloaded));
      await tester.pumpAndSettle();
      expect(reloaded.companionDisplayName, '月亮');
      await tester.tap(find.byKey(const Key('edit-companion-remark')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('companion-remark')), '未保存');
      await tester.tap(find.byTooltip('取消备注'));
      await tester.pumpAndSettle();
      expect(reloaded.companionDisplayName, '月亮');
      await tester.tap(find.byKey(const Key('edit-companion-remark')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('清空备注'));
      await tester.tap(find.byKey(const Key('save-remark')));
      await tester.pumpAndSettle();
      expect(reloaded.companionDisplayName, '小禾');
      expect(reloaded.settings['companion_note'], '');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
    variant: TargetPlatformVariant.only(TargetPlatform.windows),
  );

  testWidgets(
    'phone remark editor remains usable with keyboard and enlarged text',
    (tester) async {
      viewport(tester, const Size(320, 640));
      tester.platformDispatcher.textScaleFactorTestValue = 1.5;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final c = CompanionController();
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await tester.longPress(find.byKey(const Key('open-character-home')));
      await tester.pumpAndSettle();
      tester.view.viewInsets = const FakeViewPadding(bottom: 220);
      addTearDown(tester.view.resetViewInsets);
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('companion-remark')),
        '字' * 30,
      );
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('companion-remark')))
            .controller!
            .text
            .length,
        24,
      );
      await tester.ensureVisible(find.byKey(const Key('save-remark')));
      await tester.tap(find.byKey(const Key('save-remark')));
      await tester.pumpAndSettle();
      expect(c.companionDisplayName, '字' * 24);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
    variant: TargetPlatformVariant.only(TargetPlatform.android),
  );

  testWidgets(
    'desktop Enter sends once, Shift Enter inserts newline, and IME Enter does not send',
    (tester) async {
      viewport(tester, const Size(1280, 840));
      final c = CompanionController();
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      final input = find.byKey(const Key('message-input'));
      final before = c.messages.length;
      await tester.enterText(input, '第一行');
      await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
      await tester.pump();
      expect(c.messages.length, before);
      // A widget test has no OS text input backend. Apply the newline which
      // an unhandled Shift+Enter is allowed to deliver through that backend.
      tester.testTextInput.updateEditingValue(
        const TextEditingValue(
          text: '第一行\n',
          selection: TextSelection.collapsed(offset: 4),
        ),
      );
      expect(tester.widget<TextField>(input).controller!.text, '第一行\n');
      tester.testTextInput.updateEditingValue(
        const TextEditingValue(
          text: '正在输入',
          selection: TextSelection.collapsed(offset: 4),
          composing: TextRange(start: 0, end: 4),
        ),
      );
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pump();
      expect(c.messages.length, before);
      await tester.enterText(input, '完成输入后发送');
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await finishReply(tester);
      expect(
        c.messages.where((m) => m.isUser && m.text == '完成输入后发送'),
        hasLength(1),
      );
      expect(tester.widget<TextField>(input).controller!.text, '');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
    variant: TargetPlatformVariant.only(TargetPlatform.windows),
  );

  testWidgets(
    'sidebar filters conversations and emoji inserts at cursor without sending',
    (tester) async {
      viewport(tester, const Size(1280, 840));
      final c = CompanionController();
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('new-conversation')));
      await tester.pumpAndSettle();
      final newId = c.active!;
      await tester.enterText(
        find.byKey(const Key('conversation-filter')),
        '给今天',
      );
      await tester.pump();
      expect(find.byKey(const ValueKey('conversation-demo')), findsOneWidget);
      expect(find.byKey(ValueKey('conversation-$newId')), findsNothing);
      await tester.tap(find.byKey(const ValueKey('conversation-demo')));
      await tester.pumpAndSettle();
      expect(c.active, 'demo');
      final input = find.byKey(const Key('message-input'));
      await tester.enterText(input, '晚安。');
      tester.widget<TextField>(input).controller!.selection =
          const TextSelection.collapsed(offset: 2);
      final before = c.messages.length;
      await tester.tap(find.byKey(const Key('insert-emoji')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('emoji-🌙')));
      await tester.pumpAndSettle();
      expect(tester.widget<TextField>(input).controller!.text, '晚安🌙。');
      expect(c.messages.length, before);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
    variant: TargetPlatformVariant.only(TargetPlatform.windows),
  );

  for (final width in [880.0, 1024.0, 1440.0]) {
    testWidgets(
      'desktop toolbar and long display name fit at $width with large text',
      (tester) async {
        viewport(tester, Size(width, 800));
        tester.platformDispatcher.textScaleFactorTestValue = 1.5;
        addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
        final repository = DemoRepository();
        await repository.saveSettings({
          ...(await repository.bootstrap()).settings,
          'companion_remark': '字' * 24,
        });
        final c = CompanionController(repository: repository);
        addTearDown(c.dispose);
        await tester.pumpWidget(XinYuApp(controller: c));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(find.byKey(const Key('edit-companion-remark')), findsOneWidget);
        await tester.pumpWidget(const SizedBox());
      },
      variant: TargetPlatformVariant.only(TargetPlatform.windows),
    );
  }
}
