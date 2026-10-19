import 'dart:async';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/data/focus_interaction.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/focus_screen.dart';
import 'package:xinyu_flutter/ui/focus_style.dart';
import 'package:xinyu_flutter/ui/typography.dart';

import 'focus_test.dart' show FocusRepository;

class PresenceRepository extends FocusRepository {
  bool failPause = false, failChat = false;
  bool incomplete = false;
  Completer<void>? gate;
  String answer = '先把第一件商品的规格列出来，我们从这里开始。';
  final sent = <Map<String, dynamic>>[];
  @override
  Future<Map<String, dynamic>> focusAction(Map<String, dynamic> value) {
    if (failPause) throw const CompanionException('暂停未成功，请稍后再试。');
    return super.focusAction(value);
  }

  @override
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text, {
    List<String> imageIds = const [],
    String? quoteId,
    Map<String, dynamic>? screenContext,
  }) async* {
    sent.add({
      'conversation': conversation,
      'request': request,
      'text': text,
      'images': List.of(imageIds),
      'quote': quoteId,
    });
    await gate?.future;
    if (failChat) {
      failChat = false;
      throw const CompanionException('连接中断，请重试。');
    }
    yield {'type': 'delta', 'text': answer};
    if (incomplete) return;
    yield {
      'type': 'result',
      'result': {
        'user': {'id': '$request-user', 'content': text, 'role': 'user'},
        'assistant': {
          'id': '$request-assistant',
          'content': answer,
          'role': 'assistant',
        },
      },
    };
  }
}

const destination = String.fromEnvironment('FOCUS_REVIEW_DIR');

Future<CompanionController> mount(
  WidgetTester tester,
  PresenceRepository repo, {
  double width = 390,
  double height = 900,
  double scale = 1,
  bool reducedMotion = false,
  GlobalKey? boundary,
}) async {
  tester.view.physicalSize = Size(width, height);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  final c = CompanionController(repository: repo);
  addTearDown(c.dispose);
  await c.initialize();
  await c.focus.start('整理商品资料', 30, 5);
  await tester.pumpWidget(
    RepaintBoundary(
      key: boundary,
      child: MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          fontFamily: XinYuTypography.family,
          textTheme: XinYuTypography.textTheme,
        ),
        builder: (context, child) => MediaQuery(
          data: MediaQuery.of(context).copyWith(
            textScaler: TextScaler.linear(scale),
            disableAnimations: reducedMotion,
          ),
          child: child!,
        ),
        home: FocusScreen(controller: c),
      ),
    ),
  );
  await tester.pumpAndSettle();
  if (destination.isNotEmpty) {
    await tester.runAsync(
      () => precacheImage(
        const AssetImage(FocusStyle.background),
        tester.element(find.byType(FocusScreen)),
      ),
    );
    await tester.pumpAndSettle();
  }
  return c;
}

Future<void> tap(WidgetTester tester, String key) async {
  final finder = find.byKey(Key(key));
  await tester.ensureVisible(finder);
  await tester.tap(finder);
  await tester.pumpAndSettle();
}

Future<void> capture(
  WidgetTester tester,
  GlobalKey boundary,
  String name,
) async {
  if (destination.isEmpty) return;
  await tester.runAsync(() async {
    final render =
        boundary.currentContext!.findRenderObject()! as RenderRepaintBoundary;
    final frame = await render.toImage(pixelRatio: 1);
    final bytes = await frame.toByteData(format: ui.ImageByteFormat.png);
    await Directory(destination).create(recursive: true);
    await File('$destination/$name.png')
        .writeAsBytes(bytes!.buffer.asUint8List());
    frame.dispose();
  });
}

Future<void> close(WidgetTester tester, CompanionController c) async {
  c.focus.connect(false);
  await tester.pumpWidget(const SizedBox.shrink());
  expect(tester.takeException(), isNull);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async {
    if (destination.isEmpty) return;
    await (FontLoader(
      XinYuTypography.family,
    )..addFont(rootBundle.load(XinYuTypography.fontAsset))).load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });

  testWidgets(
    'keyboard touch shows the persisted chat reply without changing time',
    (tester) async {
      final repo = PresenceRepository();
      final c = await mount(tester, repo, reducedMotion: true);
      final session = c.focus.session!;
      final semantics = tester.ensureSemantics();
      final avatar = find.byKey(const Key('focus-touch'));
      for (var i = 0; i < 8; i++) {
        await tester.sendKeyEvent(LogicalKeyboardKey.tab);
        await tester.pump();
        if (tester
                .getSemantics(avatar)
                .getSemanticsData()
                .flagsCollection
                .isFocused ==
            ui.Tristate.isTrue) {
          break;
        }
      }
      expect(
        tester
            .getSemantics(avatar)
            .getSemanticsData()
            .flagsCollection
            .isFocused,
        ui.Tristate.isTrue,
      );
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.pumpAndSettle();
      expect(find.text(repo.answer), findsOneWidget);
      expect(
        tester
            .getSemantics(find.byKey(const Key('focus-touch')))
            .getSemanticsData()
            .hasAction(ui.SemanticsAction.tap),
        isTrue,
      );
      expect(c.focus.session!.revision, session.revision);
      expect(c.focus.session!.deadline, session.deadline);
      expect(repo.sent.single['text'], contains('我轻碰了你的头像'));
      expect(repo.sent.single['text'], contains('整理商品资料'));
      expect(repo.sent.single['conversation'], c.active);
      await tester.pump(const Duration(seconds: 8));
      expect(find.text(repo.answer), findsOneWidget);
      expect(find.text('离线规则演示 · 非模型回复'), findsOneWidget);
      semantics.dispose();
      await close(tester, c);
    },
  );

  testWidgets(
    'step needs explicit completion, survives a pause, clears for new session',
    (tester) async {
      final repo = PresenceRepository();
      final c = await mount(tester, repo);
      await tap(tester, 'focus-choose-step');
      await tap(tester, 'focus-step-save');
      expect(find.text('写下这一步，或者先不选。'), findsOneWidget);
      await tester.enterText(
        find.byKey(const Key('focus-step-input')),
        '列出第一件商品的规格',
      );
      await tap(tester, 'focus-step-save');
      await c.focus.act('pause');
      await tester.pumpAndSettle();
      expect(c.focus.presence.step, '列出第一件商品的规格');
      await tap(tester, 'focus-step-done');
      expect(find.text('你刚刚做到了'), findsOneWidget);
      expect(find.text(repo.answer), findsOneWidget);
      expect(repo.savedProgress, isNull);
      expect(repo.sent, hasLength(2));
      expect(repo.sent.last['text'], contains('列出第一件商品的规格'));
      expect(repo.sent.last['text'], contains('整体任务进度尚未确认'));
      repo.session!['id'] = 'a-new-session';
      await c.focus.refresh();
      await tester.pumpAndSettle();
      expect(c.focus.presence.lastCompletedStep, isNull);
      expect(find.byKey(const Key('focus-choose-step')), findsOneWidget);
      await close(tester, c);
    },
  );

  testWidgets(
    'stale step editor cannot write into a closed or replaced session',
    (tester) async {
      final repo = PresenceRepository();
      final c = await mount(tester, repo);
      await tap(tester, 'focus-choose-step');
      await tester.enterText(find.byKey(const Key('focus-step-input')), '旧任务');
      await c.focus.act('finish');
      await tap(tester, 'focus-step-save');
      expect(c.focus.presence.step, isNull);
      expect(c.focus.presence.setStep('不会写入结束的任务'), isFalse);
      await close(tester, c);
    },
  );

  testWidgets('shared breathing pauses first and never automatically resumes', (
    tester,
  ) async {
    final repo = PresenceRepository();
    final c = await mount(tester, repo, reducedMotion: true);
    final id = c.focus.session!.id;
    await tester.ensureVisible(find.byKey(const Key('focus-breathe')));
    await tester.tap(find.byKey(const Key('focus-breathe')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byKey(const Key('focus-break-screen')), findsOneWidget);
    expect(c.focus.session!.phase, 'focus_paused');
    await tester.pump(const Duration(seconds: 5));
    expect(find.text('慢慢呼气'), findsOneWidget);
    await tester.pump(const Duration(seconds: 17));
    expect(find.text('慢慢来，准备好再继续。'), findsOneWidget);
    await tap(tester, 'focus-break-return');
    expect(c.focus.session!.id, id);
    expect(c.focus.session!.phase, 'focus_paused');
    await tap(tester, 'focus-primary');
    expect(c.focus.session!.phase, 'focus');
    expect(repo.sent.single['text'], contains('我点击“一起缓缓”'));
    await close(tester, c);
  });

  testWidgets(
    'failed pause leaves focus visible and does not pretend to pause',
    (tester) async {
      final repo = PresenceRepository()..failPause = true;
      final c = await mount(tester, repo);
      await tap(tester, 'focus-breathe');
      expect(find.byKey(const Key('focus-break-screen')), findsNothing);
      expect(find.textContaining('暂停未成功'), findsOneWidget);
      expect(c.focus.session!.phase, 'focus');
      await tap(tester, 'focus-stuck');
      expect(find.byKey(const Key('focus-chat')), findsNothing);
      expect(repo.sent, isEmpty);
      await close(tester, c);
    },
  );

  testWidgets('company entry reconciles a remotely resumed or replaced clock', (
    tester,
  ) async {
    final repo = PresenceRepository();
    final c = await mount(tester, repo);
    await c.focus.act('pause');
    repo.session!['phase'] = 'focus';
    repo.session!['revision'] = (repo.session!['revision'] as int) + 1;
    expect(c.focus.session!.paused, isTrue);
    await tap(tester, 'focus-stuck');
    expect(repo.session!['phase'], 'focus_paused');
    expect(find.byKey(const Key('focus-chat')), findsOneWidget);
    await tap(tester, 'focus-chat-close');
    repo.session!['id'] = 'new-remote-session';
    await tap(tester, 'focus-breathe');
    expect(find.byKey(const Key('focus-break-screen')), findsNothing);
    expect(find.textContaining('这段专注已切换'), findsOneWidget);
    expect(c.focus.session!.id, 'new-remote-session');
    await close(tester, c);
  });

  testWidgets(
    'focus chat uses current conversation and leaves composer attachments intact',
    (tester) async {
      final repo = PresenceRepository();
      final c = await mount(tester, repo);
      c.updateComposer('留在主聊天的草稿');
      c.pendingImages.add('unsent-photo');
      c.pendingQuote = const QuotedMessage('quote-id', '原本要引用的话', false);
      c.focus.presence.setStep('列出第一件商品的规格');
      await tap(tester, 'focus-stuck');
      expect(repo.sent, isEmpty);
      expect(c.focus.session!.paused, isTrue);
      final input = find.byKey(const Key('focus-chat-input'));
      expect(
        tester.widget<TextField>(input).controller!.text,
        contains('整理商品资料'),
      );
      expect(
        tester.widget<TextField>(input).controller!.text,
        contains('列出第一件商品的规格'),
      );
      await tester.enterText(input, '规格太多了，先整理哪一项？');
      await tap(tester, 'focus-chat-send');
      expect(repo.sent.single['text'], '规格太多了，先整理哪一项？');
      expect(repo.sent.single['conversation'], c.active);
      expect(repo.sent.single['images'], isEmpty);
      expect(repo.sent.single['quote'], isNull);
      expect(c.composerText, '留在主聊天的草稿');
      expect(c.pendingImages, ['unsent-photo']);
      expect(c.pendingQuote!.id, 'quote-id');
      expect(find.text('先把第一件商品的规格列出来，我们从这里开始。'), findsOneWidget);
      await tap(tester, 'focus-chat-close');
      expect(c.messages.last.text, '先把第一件商品的规格列出来，我们从这里开始。');
      expect(c.focus.session!.phase, 'focus_paused');
      await close(tester, c);
    },
  );

  testWidgets('chat retries same request and setup guard keeps edited text', (
    tester,
  ) async {
    final repo = PresenceRepository()..failChat = true;
    final c = await mount(tester, repo);
    await tap(tester, 'focus-stuck');
    final input = find.byKey(const Key('focus-chat-input'));
    await tester.enterText(input, '先帮我找个切入点。');
    c.settings = {...c.settings, 'model_consent': false};
    await tap(tester, 'focus-chat-send');
    expect(repo.sent, isEmpty);
    expect(tester.widget<TextField>(input).controller!.text, '先帮我找个切入点。');
    c.settings = {...c.settings, 'model_consent': true};
    await tap(tester, 'focus-chat-send');
    expect(find.text('连接中断，请重试。'), findsOneWidget);
    await tap(tester, 'focus-chat-retry');
    expect(repo.sent.length, 2);
    expect(repo.sent[0]['request'], repo.sent[1]['request']);
    expect(c.messages.where((line) => line.text == '先帮我找个切入点。').length, 1);
    await tap(tester, 'focus-chat-close');
    await close(tester, c);
  });

  testWidgets(
    'pending touch is single flight and stale replies stay out of a new phase',
    (tester) async {
      final repo = PresenceRepository()..gate = Completer<void>();
      final c = await mount(tester, repo);
      c.updateComposer('还没有发送的文字');
      c.pendingImages.add('photo');
      c.pendingQuote = const QuotedMessage('quote', '引用', false);
      await tap(tester, 'focus-touch');
      expect(find.text('正在回应…'), findsOneWidget);
      expect(find.text(repo.answer), findsNothing);
      await c.interactWithFocus(FocusInteraction.touch);
      expect(repo.sent, hasLength(1));
      expect(repo.sent.single['images'], isEmpty);
      expect(repo.sent.single['quote'], isNull);
      await c.focus.act('pause');
      repo.gate!.complete();
      await tester.pumpAndSettle();
      expect(c.messages.last.text, repo.answer);
      expect(c.focus.presence.response, isNull);
      expect(find.text('计时已暂停'), findsOneWidget);
      expect(c.composerText, '还没有发送的文字');
      expect(c.pendingImages, ['photo']);
      expect(c.pendingQuote!.id, 'quote');
      await close(tester, c);
    },
  );

  testWidgets(
    'failed completion has no canned reply and retry preserves the same action',
    (tester) async {
      final repo = PresenceRepository()..failChat = true;
      final c = await mount(tester, repo);
      c.focus.presence.setStep('只列出尺寸');
      await tester.pumpAndSettle();
      await tap(tester, 'focus-step-done');
      expect(c.focus.presence.lastCompletedStep, '只列出尺寸');
      expect(c.focus.presence.response, isNull);
      expect(find.text('连接中断，请重试。'), findsOneWidget);
      expect(find.text('收到，这一小步已经走过了。'), findsNothing);
      await tap(tester, 'focus-reply-retry');
      expect(repo.sent, hasLength(2));
      expect(repo.sent.first['request'], repo.sent.last['request']);
      expect(repo.sent.first['text'], repo.sent.last['text']);
      expect(
        c.messages.where((line) => line.text.contains('确认下面这个小步骤已经完成')),
        hasLength(1),
      );
      expect(find.text(repo.answer), findsOneWidget);
      expect(c.focus.presence.step, isNull);
      await close(tester, c);
    },
  );

  testWidgets('incomplete stream is not shown as a companion reply', (
    tester,
  ) async {
    final repo = PresenceRepository()..incomplete = true;
    final c = await mount(tester, repo);
    await tap(tester, 'focus-touch');
    expect(c.focus.presence.response, isNull);
    expect(find.text(repo.answer), findsNothing);
    expect(find.text('回复未完整返回，请重试。'), findsOneWidget);
    expect(find.byKey(const Key('focus-reply-retry')), findsOneWidget);
    await close(tester, c);
  });

  testWidgets(
    'consent guard sends no interaction and switching chats clears its reply',
    (tester) async {
      final repo = PresenceRepository();
      final c = await mount(tester, repo);
      c.settings = {...c.settings, 'model_consent': false};
      await c.interactWithFocus(FocusInteraction.chooseStep, step: '未同意的步骤');
      expect(repo.sent, isEmpty);
      expect(c.focus.presence.step, isNull);
      c.settings = {...c.settings, 'model_consent': true};
      await c.interactWithFocus(FocusInteraction.touch);
      expect(c.focus.presence.response, repo.answer);
      await c.select('another-conversation');
      await tester.pumpAndSettle();
      expect(c.focus.presence.response, isNull);
      await close(tester, c);
    },
  );

  for (final width in [320.0, 390.0, 768.0, 1024.0, 1440.0]) {
    testWidgets(
      'interactive focus renders and actions remain reachable at $width',
      (tester) async {
        final boundary = GlobalKey();
        final c = await mount(
          tester,
          PresenceRepository(),
          width: width,
          height: width < 500 ? 900 : 960,
          boundary: boundary,
        );
        c.focus.presence.setStep('把第一件商品的规格列出来');
        await tester.pumpAndSettle();
        await tester.pump(const Duration(seconds: 8));
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        await capture(tester, boundary, 'focus-interactive-${width.toInt()}');
        if (width == 390) {
          await tester.tap(find.byKey(const Key('focus-breathe')));
          await tester.pump();
          await tester.pump(const Duration(milliseconds: 800));
          await capture(tester, boundary, 'focus-breathing-390');
          await tester.sendKeyEvent(LogicalKeyboardKey.escape);
          await tester.pumpAndSettle();
          expect(c.focus.session!.paused, isTrue);
          await tap(tester, 'focus-stuck');
          await capture(tester, boundary, 'focus-discuss-390');
          await tap(tester, 'focus-chat-close');
        }
        await tap(tester, 'focus-step-done');
        await close(tester, c);
      },
    );
  }

  testWidgets(
    '320px double text and keyboard keep companionship actions accessible',
    (tester) async {
      final c = await mount(
        tester,
        PresenceRepository(),
        width: 320,
        height: 640,
        scale: 2,
      );
      await tap(tester, 'focus-stuck');
      tester.view.viewInsets = const FakeViewPadding(bottom: 240);
      await tester.pumpAndSettle();
      final input = find.byKey(const Key('focus-chat-input'));
      await tester.ensureVisible(input);
      await tester.enterText(input, '一起看看下一步。');
      await tap(tester, 'focus-chat-send');
      expect(tester.takeException(), isNull);
      tester.view.resetViewInsets();
      await tester.pumpAndSettle();
      await tap(tester, 'focus-chat-close');
      await tap(tester, 'focus-breathe');
      expect(tester.takeException(), isNull);
      await tap(tester, 'focus-break-return');
      await close(tester, c);
    },
  );
}
