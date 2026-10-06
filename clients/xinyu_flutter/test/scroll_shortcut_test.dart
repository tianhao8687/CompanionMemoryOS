import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

class ScrollControllerFixture extends CompanionController {
  void incoming() {
    messages = [
      ...messages,
      const ChatLine(
        id: 'new-below-reader',
        text: '合成的新消息，等你看完再聊。',
        isUser: false,
        sequence: 1000,
      ),
    ];
    notifyListeners();
  }
}

void main() {
  testWidgets(
    'empty conversation keeps the shortcut visible and enables it after first message',
    (tester) async {
      final c = ScrollControllerFixture();
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await c.newConversation();
      await tester.pumpAndSettle();
      final button = find.byKey(const Key('back-to-bottom'));
      expect(button, findsOneWidget);
      expect(tester.widget<TextButton>(button).onPressed, isNull);
      await tester.enterText(find.byKey(const Key('message-input')), '第一句话');
      await tester.pump();
      await tester.tap(find.byKey(const Key('send-message')));
      for (var i = 0; i < 80; i++) {
        await tester.pump(const Duration(milliseconds: 40));
      }
      expect(tester.widget<TextButton>(button).onPressed, isNotNull);
      expect(button.hitTestable(), findsOneWidget);
      expect(
        tester
            .widget<ListView>(find.byKey(const Key('chat-list')))
            .controller!
            .offset,
        0,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
  for (final size in [
    const Size(320, 640),
    const Size(390, 844),
    const Size(1280, 800),
  ]) {
    testWidgets(
      'bottom shortcut stays accessible at latest, short scroll and keyboard ${size.width}',
      (tester) async {
        tester.view.physicalSize = size;
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        addTearDown(tester.view.resetViewInsets);
        final c = ScrollControllerFixture();
        addTearDown(c.dispose);
        await tester.pumpWidget(XinYuApp(controller: c));
        await tester.pumpAndSettle();
        await c.benchmark();
        await tester.pumpAndSettle();
        final button = find.byKey(const Key('back-to-bottom'));
        final list = find.byKey(const Key('chat-list'));
        final scroll = tester.widget<ListView>(list).controller!;
        expect(scroll.offset, 0);
        expect(button.hitTestable(), findsOneWidget);
        // The shortcut has its own space: it must not cover a message or the input.
        expect(
          tester.getRect(button).top,
          greaterThanOrEqualTo(tester.getRect(list).bottom),
        );
        expect(
          tester.getRect(button).bottom,
          lessThanOrEqualTo(
            tester.getRect(find.byKey(const Key('message-input'))).top,
          ),
        );
        scroll.jumpTo(48);
        await tester.pumpAndSettle();
        expect(scroll.offset, closeTo(48, 1));
        expect(c.atLatest, isFalse);
        expect(button.hitTestable(), findsOneWidget);
        await tester.tap(button);
        await tester.pumpAndSettle();
        expect(scroll.offset, 0);
        expect(c.atLatest, isTrue);
        expect(button.hitTestable(), findsOneWidget);

        tester.view.viewInsets = const FakeViewPadding(bottom: 220);
        await tester.pumpAndSettle();
        await tester.enterText(
          find.byKey(const Key('message-input')),
          '键盘打开时保留草稿',
        );
        await tester.pump();
        // Use a real drag as well as a programmatic position, with the keyboard open.
        await tester.drag(list, const Offset(0, 180));
        await tester.pumpAndSettle();
        expect(scroll.offset, greaterThan(0));
        expect(button.hitTestable(), findsOneWidget);
        expect(tester.getRect(button).bottom, lessThan(size.height - 220));
        await tester.tap(button);
        await tester.pumpAndSettle();
        expect(scroll.offset, 0);
        expect(
          tester
              .widget<TextField>(find.byKey(const Key('message-input')))
              .controller!
              .text,
          '键盘打开时保留草稿',
        );
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }

  testWidgets(
    'slight scroll preserves reader when a reply arrives and shortcut clears unread count',
    (tester) async {
      final c = ScrollControllerFixture();
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await c.benchmark();
      await tester.pumpAndSettle();
      final scroll = tester
          .widget<ListView>(find.byKey(const Key('chat-list')))
          .controller!;
      scroll.jumpTo(48);
      await tester.pumpAndSettle();
      expect(c.viewState['anchor_id'], isNotNull);
      final anchor = c.viewState['anchor_id'] as String;
      final before = c.viewState['anchor_y'] as double;
      c.incoming();
      await tester.pumpAndSettle();
      expect(c.atLatest, isFalse);
      expect(c.viewState['anchor_id'], anchor);
      expect(c.viewState['anchor_y'] as double, closeTo(before, 2));
      expect(find.text('1 条新消息'), findsOneWidget);
      await tester.tap(find.byKey(const Key('back-to-bottom')));
      await tester.pumpAndSettle();
      expect(scroll.offset, 0);
      expect(find.text('1 条新消息'), findsNothing);
      expect(find.text('回到底部'), findsOneWidget);
      expect(c.viewState['anchor_id'], isNull);
      expect(c.viewState['scroll_offset'], 0);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
