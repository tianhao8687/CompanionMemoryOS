import 'settings_navigation.dart';

import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/local_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/state/focus_controller.dart';
import 'package:xinyu_flutter/ui/focus_setup.dart';
import 'package:xinyu_flutter/ui/focus_screen.dart';
import 'package:xinyu_flutter/ui/focus_style.dart';
import 'package:xinyu_flutter/ui/nook_sheet.dart';
import 'package:xinyu_flutter/ui/typography.dart';

class FocusRepository extends LocalRepository {
  FocusRepository() : super('http://127.0.0.1:12345');
  Map<String, dynamic>? session;
  final requests = <String>[];
  bool loseReply = false, stale = false;
  String notice = 'once';
  int noticeClaims = 0;
  String? savedProgress;
  Map<String, dynamic> snapshot() => {
    'session': session == null ? null : {...session!},
    'server_now': DateTime.now().millisecondsSinceEpoch / 1000,
    'history': [],
    'preferences': {'focus_sound': 'silent', 'focus_notice': notice},
  };
  @override
  Future<Snapshot> bootstrap() async => const Snapshot(
    {
      'companion_name': '小禾',
      'storage_consent': true,
      'model_consent': true,
      'model_mode': 'offline',
    },
    [Conversation('test', '这一会儿')],
    capabilities: {'focus_features': true, 'nook_features': true},
  );
  @override
  Future<MessagePage> messages(String conversation, {int? before}) async =>
      const MessagePage([
        ChatLine(id: 'one', text: '我得把商品资料整理一下，你陪我半小时。', isUser: true),
        ChatLine(
          id: 'two',
          text: '好。准备好了就开始。',
          isUser: false,
          focusProposal: {
            'intention': '整理商品资料',
            'focus_minutes': 30,
            'rest_minutes': 5,
          },
        ),
      ]);
  @override
  Future<Map<String, dynamic>> focus(String conversation) async => snapshot();
  @override
  Future<Map<String, dynamic>> startFocus(Map<String, dynamic> value) async {
    requests.add(value['request_id'] as String);
    if (session != null && ['done', 'ended'].contains(session!['phase'])) {
      session = null;
    }
    session ??= {
      'id': 'session',
      'revision': 1,
      'phase': 'focus',
      'intention': value['intention'],
      'focus_minutes': value['focus_minutes'],
      'remaining_seconds': (value['focus_minutes'] as int) * 60,
      'deadline':
          DateTime.now().millisecondsSinceEpoch / 1000 +
          (value['focus_minutes'] as int) * 60,
      'ended_at': null,
    };
    if (loseReply) {
      loseReply = false;
      throw const CompanionException('连接中断，请重试。');
    }
    return snapshot();
  }

  @override
  Future<Map<String, dynamic>> focusAction(Map<String, dynamic> value) async {
    if (stale) {
      stale = false;
      session!['revision'] = 7;
      session!['phase'] = 'focus_paused';
      session!['deadline'] = null;
      throw const CompanionException('另一窗口已改变计时。');
    }
    expect(value['revision'], session!['revision']);
    session!['revision'] = (session!['revision'] as int) + 1;
    final resting = (session!['phase'] as String).startsWith('rest');
    session!['phase'] = switch (value['action']) {
      'pause' => resting ? 'rest_paused' : 'focus_paused',
      'resume' => resting ? 'rest' : 'focus',
      'finish' => 'ended',
      'rest' => 'rest',
      _ => 'focus',
    };
    if (['rest', 'extend'].contains(value['action'])) {
      session!['remaining_seconds'] = 300;
    }
    session!['deadline'] = ['focus', 'rest'].contains(session!['phase'])
        ? DateTime.now().millisecondsSinceEpoch / 1000 +
              (session!['remaining_seconds'] as num)
        : null;
    return snapshot();
  }

  @override
  Future<Map<String, dynamic>> focusProgress(Map<String, dynamic> value) async {
    savedProgress = value['content'] as String;
    return {};
  }

  void elapsed({int age = 0}) {
    session!['phase'] = 'focus_done';
    session!['revision'] = (session!['revision'] as int) + 1;
    session!['deadline'] = null;
    session!['remaining_seconds'] = 0;
    session!['ended_at'] = DateTime.now().millisecondsSinceEpoch / 1000 - age;
  }

  @override
  Future<Map<String, dynamic>> focusPreference(
    Map<String, dynamic> value,
  ) async {
    notice = value['value'] as String;
    return snapshot();
  }

  @override
  Future<bool> claimFocusNotice(String id, int revision) async {
    noticeClaims++;
    if (session!['notice_revision'] == revision) return false;
    session!['notice_revision'] = revision;
    return true;
  }

  @override
  Future<Map<String, dynamic>> nook({String? at}) async => {
    'items': [],
    'timeline': [],
    'enabled': false,
    'daily_limit': 3,
    'busy': false,
    'message': '',
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  const destination = String.fromEnvironment('FOCUS_REVIEW_DIR');
  setUpAll(() async {
    if (destination.isEmpty) return;
    await (FontLoader(
      XinYuTypography.family,
    )..addFont(rootBundle.load(XinYuTypography.fontAsset))).load();
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
  });
  test('confirmation survives decoding and bookmarking', () {
    final line = ChatLine.fromJson({
      'id': 'm',
      'role': 'assistant',
      'content': '准备好了就开始。',
      'focus_proposal': {
        'intention': '整理资料',
        'focus_minutes': 30,
        'rest_minutes': 5,
      },
    });
    expect(line.withBookmark(true).focusProposal!['focus_minutes'], 30);
  });
  test(
    'disabled focus does not access a native engine before it starts',
    () async {
      final focus = FocusController(
        () => throw StateError('Not ready'),
        () => null,
      );
      addTearDown(focus.dispose);
      await focus.refresh();
      expect(await focus.start('', 30, 5), false);
    },
  );
  test(
    'lost start reply reuses request; stale action reconciles with server',
    () async {
      final repo = FocusRepository()..loseReply = true;
      final focus = FocusController(() => repo, () => 'test')..connect(true);
      addTearDown(focus.dispose);
      addTearDown(repo.close);
      await Future<void>.delayed(Duration.zero);
      expect(await focus.start('', 30, 5), false);
      expect(focus.session!.id, 'session');
      expect(await focus.start('', 30, 5), true);
      expect(repo.requests[0], repo.requests[1]);
      repo.stale = true;
      expect(await focus.act('pause'), false);
      expect(focus.session!.revision, 7);
      expect(focus.session!.paused, true);
      expect(await focus.act('resume'), true);
      focus.connect(false);
      expect(focus.session, null);
    },
  );
  testWidgets('editable form validates duration and accepts an empty task', (
    tester,
  ) async {
    final repo = FocusRepository();
    final c = CompanionController(repository: repo)..active = 'test';
    c.focus.connect(true);
    addTearDown(c.dispose);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: FocusSetup(controller: c)),
      ),
    );
    await tester.enterText(find.byKey(const Key('focus-minutes')), '0');
    await tester.tap(find.byKey(const Key('focus-start')));
    await tester.pump();
    expect(repo.session, null);
    await tester.enterText(find.byKey(const Key('focus-minutes')), '15');
    await tester.tap(find.byKey(const Key('focus-start')));
    await tester.pump();
    expect(repo.session!['intention'], '');
    expect(repo.session!['focus_minutes'], 15);
    c.focus.connect(false);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  test(
    'native notices respect once, off, old deadlines and foreground',
    () async {
      final repo = FocusRepository();
      final focus = FocusController(() => repo, () => 'test')..connect(true);
      addTearDown(focus.dispose);
      addTearDown(repo.close);
      final messages = <String>[];
      focus.announcement.addListener(() {
        if (focus.announcement.value case final String text) messages.add(text);
      });
      await Future<void>.delayed(Duration.zero);
      await focus.start('', 30, 5);
      repo.elapsed();
      await focus.refresh();
      await focus.refresh();
      expect(messages, ['30 分钟到了。']);
      expect(repo.noticeClaims, 1);
      focus.announcement.value = null;
      await focus.notice(false);
      repo.elapsed();
      await focus.refresh();
      expect(messages.length, 1);
      expect(repo.noticeClaims, 1);
      repo.elapsed(age: 121);
      await focus.notice(true);
      await focus.refresh();
      expect(messages.length, 1);
      focus.setForeground(false);
      repo.elapsed();
      await focus.refresh();
      expect(repo.noticeClaims, 1);
      focus.setForeground(true);
      await Future<void>.delayed(Duration.zero);
      expect(messages.length, 2);
      expect(repo.noticeClaims, 2);
    },
  );

  testWidgets('returning to the app refreshes the clock and shows one notice', (
    tester,
  ) async {
    final repo = FocusRepository();
    final c = CompanionController(repository: repo);
    addTearDown(c.dispose);
    await tester.pumpWidget(XinYuApp(controller: c));
    await tester.pumpAndSettle();
    await c.focus.start('', 30, 5);
    for (final state in [
      AppLifecycleState.inactive,
      AppLifecycleState.hidden,
      AppLifecycleState.paused,
    ]) {
      tester.binding.handleAppLifecycleStateChanged(state);
    }
    repo.elapsed();
    await c.focus.refresh();
    expect(repo.noticeClaims, 0);
    for (final state in [
      AppLifecycleState.hidden,
      AppLifecycleState.inactive,
      AppLifecycleState.resumed,
    ]) {
      tester.binding.handleAppLifecycleStateChanged(state);
    }
    await tester.pumpAndSettle();
    expect(find.byType(SnackBar), findsOneWidget);
    expect(find.text('30 分钟到了。'), findsOneWidget);
    await c.focus.refresh();
    await tester.pump();
    expect(repo.noticeClaims, 1);
    c.focus.connect(false);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  for (final width in [320.0, 390.0, 768.0, 1024.0, 1440.0, 1536.0]) {
    testWidgets('chat and independent fullscreen share one clock at $width', (
      tester,
    ) async {
      final height = width == 1536
          ? 1024.0
          : width < 500
          ? 900.0
          : 960.0;
      tester.view.physicalSize = Size(width, height);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final c = CompanionController(repository: FocusRepository());
      addTearDown(c.dispose);
      final boundary = GlobalKey();
      await tester.pumpWidget(
        RepaintBoundary(
          key: boundary,
          child: XinYuApp(controller: c),
        ),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(Key(width < 880 ? 'compose-more' : 'open-focus')),
        findsOneWidget,
      );
      await c.focus.start('整理商品资料', 30, 5);
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('focus-status')), findsOneWidget);
      Future<void> capture(String name) async {
        if (destination.isEmpty) return;
        await tester.runAsync(() async {
          final render =
              boundary.currentContext!.findRenderObject()!
                  as RenderRepaintBoundary;
          final frame = await render.toImage(
            pixelRatio: width == 1536 ? 1 : 1.5,
          );
          final data = await frame.toByteData(format: ui.ImageByteFormat.png);
          await Directory(destination).create(recursive: true);
          await File('$destination/$name.png')
              .writeAsBytes(data!.buffer.asUint8List());
          frame.dispose();
        });
      }

      await capture('flutter-chat-${width.toInt()}');
      await composeAction(tester, 'open-focus');
      await tester.pumpAndSettle();
      await tester.runAsync(
        () => precacheImage(
          const AssetImage(FocusStyle.background),
          tester.element(find.byType(FocusScreen)),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.byType(NookSheet), findsNothing);
      expect(
        tester.getRect(find.byKey(const Key('focus-screen'))),
        Rect.fromLTWH(0, 0, width, height),
      );
      expect(tester.takeException(), isNull);
      await capture('flutter-focus-${width.toInt()}');
      await tester.ensureVisible(find.text('暂停'));
      await tester.tap(find.text('暂停'));
      await tester.pumpAndSettle();
      expect(c.focus.session!.phase, 'focus_paused');
      if (width == 390) {
        await capture('flutter-focus-paused-390');
        await tester.tap(find.byTooltip('更多专注操作'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('提醒设置'));
        await tester.pumpAndSettle();
        await tester.tap(find.byType(SwitchListTile));
        await tester.pumpAndSettle();
        expect(c.focus.preferences['focus_notice'], 'off');
        await tester.tap(find.text('完成'));
        await tester.pumpAndSettle();
        await tester.tap(find.byTooltip('更多专注操作'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('活动记录'));
        await tester.pumpAndSettle();
        expect(find.byType(FocusScreen), findsOneWidget);
        await tester.tap(find.text('关闭'));
        await tester.pumpAndSettle();
      }
      await tester.tap(find.byKey(const Key('focus-back')));
      await tester.pumpAndSettle();
      expect(find.textContaining('已暂停'), findsOneWidget);
      expect(tester.takeException(), isNull);
      c.focus.connect(false);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }

  testWidgets('fullscreen setup, arrival choices and explicit progress work', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final repo = FocusRepository();
    final c = CompanionController(repository: repo);
    addTearDown(c.dispose);
    final boundary = GlobalKey();
    await tester.pumpWidget(
      RepaintBoundary(
        key: boundary,
        child: XinYuApp(controller: c),
      ),
    );
    await tester.pumpAndSettle();
    await composeAction(tester, 'open-focus');
    await tester.pumpAndSettle();
    expect(repo.session, isNull);
    expect(find.byType(FocusScreen), findsOneWidget);
    await tester.runAsync(
      () => precacheImage(
        const AssetImage(FocusStyle.background),
        tester.element(find.byType(FocusScreen)),
      ),
    );
    await tester.pumpAndSettle();
    Future<void> capture(String state) async {
      if (destination.isEmpty) return;
      await tester.runAsync(() async {
        final render =
            boundary.currentContext!.findRenderObject()!
                as RenderRepaintBoundary;
        final frame = await render.toImage(pixelRatio: 1.5);
        final bytes = await frame.toByteData(format: ui.ImageByteFormat.png);
        await File('$destination/flutter-focus-$state-390.png')
            .writeAsBytes(bytes!.buffer.asUint8List());
        frame.dispose();
      });
    }

    await capture('setup');
    await tester.enterText(find.byKey(const Key('focus-task')), '整理商品资料');
    await tester.enterText(find.byKey(const Key('focus-minutes')), '1');
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('focus-start')));
    await tester.tap(find.byKey(const Key('focus-start')));
    tester.view.resetViewInsets();
    await tester.pumpAndSettle();
    expect(c.focus.session!.minutes, 1);
    expect(find.text('专注于眼前这一小步'), findsOneWidget);
    await tester.tap(find.byKey(const Key('focus-back')));
    await tester.pumpAndSettle();
    await tester.tap(find.textContaining('专注中'));
    await tester.pumpAndSettle();
    expect(repo.requests.length, 1);
    expect(find.byType(FocusScreen), findsOneWidget);
    repo.elapsed();
    await c.focus.refresh();
    await tester.pumpAndSettle();
    await tester.pump(const Duration(seconds: 6));
    await tester.pumpAndSettle();
    await capture('arrived');
    await tester.tap(find.byKey(const Key('focus-extend')));
    await tester.pumpAndSettle();
    expect(c.focus.session!.phase, 'focus');
    expect(c.focus.seconds, inInclusiveRange(299, 300));
    repo.elapsed();
    await c.focus.refresh();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('focus-primary')));
    await tester.pumpAndSettle();
    expect(c.focus.session!.phase, 'rest');
    await tester.pump(const Duration(seconds: 6));
    await tester.pumpAndSettle();
    await capture('rest');
    await tester.tap(find.byKey(const Key('focus-primary')));
    await tester.pumpAndSettle();
    expect(c.focus.session!.phase, 'rest_paused');
    await tester.tap(find.byKey(const Key('focus-primary')));
    await tester.pumpAndSettle();
    expect(c.focus.session!.phase, 'rest');
    await tester.tap(find.byKey(const Key('focus-finish')));
    await tester.pumpAndSettle();
    expect(c.focus.session!.phase, 'ended');
    expect(repo.savedProgress, isNull);
    await capture('ended');
    await tester.tap(find.text('留下一点进展'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '把三件商品的规格整理好了。');
    await tester.tap(find.text('收进记忆手札'));
    await tester.pumpAndSettle();
    expect(repo.savedProgress, '把三件商品的规格整理好了。');
    await tester.tap(find.byKey(const Key('focus-primary')));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('focus-start')));
    await tester.tap(find.byKey(const Key('focus-start')));
    await tester.pumpAndSettle();
    expect(c.focus.session!.phase, 'focus');
    expect(repo.requests.length, 2);
    expect(tester.takeException(), isNull);
    c.focus.connect(false);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('chat confirmation enters fullscreen only after explicit start', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1024, 960);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final c = CompanionController(repository: FocusRepository());
    addTearDown(c.dispose);
    await tester.pumpWidget(XinYuApp(controller: c));
    await tester.pumpAndSettle();
    expect(c.focus.session, isNull);
    final card = find.byKey(const ValueKey('focus-proposal-two'));
    final button = find.descendant(
      of: card,
      matching: find.byKey(const Key('focus-start')),
    );
    await tester.ensureVisible(button);
    await tester.tap(button);
    await tester.pumpAndSettle();
    expect(find.byType(FocusScreen), findsOneWidget);
    expect(c.focus.session!.intention, '整理商品资料');
    await tester.sendKeyEvent(LogicalKeyboardKey.escape);
    await tester.pumpAndSettle();
    expect(find.byType(FocusScreen), findsNothing);
    expect(c.focus.session!.phase, 'focus');
    c.focus.connect(false);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('short phone and double-size text keep focus actions reachable', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(320, 640);
    tester.view.devicePixelRatio = 1;
    tester.platformDispatcher.textScaleFactorTestValue = 2;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    final c = CompanionController(repository: FocusRepository());
    addTearDown(c.dispose);
    await tester.pumpWidget(XinYuApp(controller: c));
    await tester.pumpAndSettle();
    await c.focus.start('整理今天新收到的商品资料和图片', 30, 5);
    await composeAction(tester, 'open-focus');
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.ensureVisible(find.byKey(const Key('focus-primary')));
    expect(
      find.byKey(const Key('focus-primary')).hitTestable(),
      findsOneWidget,
    );
    expect(find.byKey(const Key('focus-back')).hitTestable(), findsOneWidget);
    await tester.tap(find.byKey(const Key('focus-primary')));
    await tester.pumpAndSettle();
    expect(c.focus.session!.phase, 'focus_paused');
    await tester.tap(find.byTooltip('更多专注操作'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('提醒设置'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.tap(find.text('完成'));
    await tester.pumpAndSettle();
    c.focus.connect(false);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
