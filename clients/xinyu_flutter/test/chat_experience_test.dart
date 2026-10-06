import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/demo_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/chat.dart';

class IncomingController extends CompanionController {
  IncomingController({super.repository});
  void incoming() {
    messages = [
      ...messages,
      ChatLine(
        id: 'incoming',
        text: '这是一条新的合成消息\n\n你慢慢看。',
        isUser: false,
        sequence: 1000,
      ),
    ];
    notifyListeners();
  }
}

Future<void> ticks(WidgetTester tester, [int count = 80]) async {
  for (var i = 0; i < count; i++) {
    await tester.pump(const Duration(milliseconds: 40));
  }
}

Finder bubble(String id) =>
    find.byWidgetPredicate((w) => w is MessageBubble && w.line.id == id);

void main() {
  testWidgets(
    'message menu bookmarks, multi-copy and character collection; no resend action',
    (tester) async {
      final c = CompanionController();
      addTearDown(c.dispose);
      String clipboard = '';
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            clipboard = (call.arguments as Map)['text'] as String;
          }
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      final last = c.messages.last;
      await tester.longPress(bubble(last.id));
      await tester.pumpAndSettle();
      expect(find.text('重发'), findsNothing);
      expect(find.text('重新生成'), findsNothing);
      await tester.tap(find.text('收藏'));
      await tester.pumpAndSettle();
      expect(c.messages.last.bookmarked, isTrue);
      await tester.longPress(bubble(last.id));
      await tester.pumpAndSettle();
      await tester.tap(find.text('多选'));
      await tester.pumpAndSettle();
      final other = c.messages[c.messages.length - 2];
      await tester.tap(find.byKey(ValueKey('select-${other.id}')));
      await tester.pump();
      expect(c.selectedMessages, {last.id, other.id});
      await tester.tap(find.byKey(const Key('copy-selected')));
      await tester.pumpAndSettle();
      expect(clipboard, contains(last.text));
      expect(
        clipboard.indexOf(other.text),
        lessThan(clipboard.indexOf(last.text)),
      );
      expect(c.selecting, isFalse);
      await tester.tap(find.byKey(const Key('open-character-home')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('open-bookmarks')));
      await tester.tap(find.byKey(const Key('open-bookmarks')));
      await tester.pumpAndSettle();
      expect(find.text('收藏夹'), findsWidgets);
      expect(find.text(last.text), findsWidgets);
      await tester.tap(find.text('取消收藏'));
      await tester.pumpAndSettle();
      expect(c.messages.last.bookmarked, isFalse);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'draft and reader anchor survive conversation switching; incoming does not steal position',
    (tester) async {
      final repository = DemoRepository();
      final c = IncomingController(repository: repository);
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await c.benchmark();
      await tester.pumpAndSettle();
      final first = c.active!;
      var scroll = tester
          .widget<ListView>(find.byKey(const Key('chat-list')))
          .controller!;
      scroll.jumpTo(1500);
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('message-input')),
        '这段草稿留在旧会话',
      );
      await tester.pump(const Duration(milliseconds: 350));
      final saved = c.viewState;
      final anchor = saved['anchor_id'] as String;
      final y = tester.getTopLeft(bubble(anchor)).dy;
      c.incoming();
      await tester.pumpAndSettle();
      expect(tester.getTopLeft(bubble(anchor)).dy, closeTo(y, 2));
      expect(find.text('1 条新消息'), findsOneWidget);
      // Restore from the repository state too, not only a widget's in-memory offset.
      await c.newConversation();
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('message-input')))
            .controller!
            .text,
        '',
      );
      await tester.enterText(
        find.byKey(const Key('message-input')),
        '新会话自己的草稿',
      );
      await c.select(first);
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('message-input')))
            .controller!
            .text,
        '这段草稿留在旧会话',
      );
      scroll = tester
          .widget<ListView>(find.byKey(const Key('chat-list')))
          .controller!;
      expect(scroll.offset, greaterThan(100));
      expect(bubble(anchor), findsOneWidget);
      await tester.tap(find.byKey(const Key('back-to-bottom')));
      await tester.pumpAndSettle();
      expect(scroll.offset, 0);
      expect(
        find.byKey(const Key('back-to-bottom')).hitTestable(),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'natural cadence batches rapid input once and cancel restores text; toggle is immediate',
    (tester) async {
      final c = CompanionController();
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      for (final text in ['今天去了海边', '还捡到一颗贝壳']) {
        await tester.enterText(find.byKey(const Key('message-input')), text);
        await tester.pump();
        await tester.tap(find.byKey(const Key('send-message')));
        await tester.pump();
      }
      expect(c.collecting, isTrue);
      expect(c.sending, isFalse);
      await tester.tap(find.byKey(const Key('send-collected')));
      await ticks(tester);
      expect(
        c.messages.where((m) => m.isUser && m.text == '今天去了海边\n\n还捡到一颗贝壳'),
        hasLength(1),
      );
      expect(c.messages.last.text, contains('示例回复'));
      // Model-authored paragraphs are displayed separately, with the original intact.
      expect(find.text('我在，慢慢说就好。'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('message-input')), '先不发这条');
      await tester.pump();
      await tester.tap(find.byKey(const Key('send-message')));
      await tester.pump();
      await tester.tap(find.byTooltip('收回到草稿'));
      await tester.pumpAndSettle();
      expect(c.collecting, isFalse);
      expect(
        tester
            .widget<TextField>(find.byKey(const Key('message-input')))
            .controller!
            .text,
        '先不发这条',
      );
      await c.save({...c.settingsCopy(), 'natural_chat': false});
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('send-message')));
      await tester.pump();
      expect(c.collecting, isFalse);
      expect(c.sending, isTrue);
      await ticks(tester);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'character home edits only selected profile and fits small screen with keyboard',
    (tester) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final c = CompanionController();
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-character-home')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('edit-character')));
      await tester.tap(find.byKey(const Key('edit-character')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('profile-name')), '小棠');
      await tester.enterText(
        find.byKey(const Key('profile-bio')),
        '虚构人物，喜欢看海。',
      );
      tester.view.viewInsets = const FakeViewPadding(bottom: 220);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
      await tester.tap(find.byKey(const Key('save-character')));
      await tester.pumpAndSettle();
      tester.view.resetViewInsets();
      await tester.pumpAndSettle();
      expect(c.companionName, '小棠');
      expect(c.settings['persona_notes'], '虚构人物，喜欢看海。');
      expect(c.userName, '');
      await Scrollable.ensureVisible(
        tester.element(find.text('我的主页')),
        alignment: .5,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('我的主页'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('edit-character')));
      await tester.tap(find.byKey(const Key('edit-character')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('profile-name')), '我自己的称呼');
      await tester.tap(find.byTooltip('取消编辑资料'));
      await tester.pumpAndSettle();
      expect(c.userName, '');
      expect(c.companionName, '小棠');
      await tester.tap(find.byTooltip('关闭角色主页'));
      await tester.pumpAndSettle();
      final source = c.messages.where((m) => m.isUser).last;
      final content = find.descendant(
        of: bubble(source.id),
        matching: find.text(source.text),
      );
      await Scrollable.ensureVisible(tester.element(content), alignment: .5);
      await tester.pumpAndSettle();
      await tester.longPress(content);
      await tester.pumpAndSettle();
      expect(find.text('复制文字'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
