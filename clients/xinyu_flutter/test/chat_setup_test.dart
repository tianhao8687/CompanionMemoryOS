import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/demo_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/settings_sheet.dart';

// Deterministic capability/transport double. No provider credentials or calls.
class SetupRepository extends DemoRepository {
  bool keyConfigured = false;
  bool failSave = false;
  bool failBootstrap = false;
  String? sendFailure;
  int sends = 0;

  @override
  bool get isDemo => false;

  @override
  Future<Snapshot> bootstrap() async {
    if (failBootstrap) {
      throw const CompanionException('本机引擎启动失败，请重新连接。');
    }
    final snapshot = await super.bootstrap();
    return Snapshot(
      snapshot.settings,
      snapshot.conversations,
      capabilities: {
        ...snapshot.capabilities,
        'model_ready':
            snapshot.settings['model_mode'] == 'offline' || keyConfigured,
        'key_configured': keyConfigured,
        'vision_ready': false,
      },
    );
  }

  @override
  Future<Map<String, dynamic>> saveSettings(
    Map<String, dynamic> settings, {
    String? apiKey,
    bool? rememberKey,
    bool clearKey = false,
  }) {
    if (failSave) throw const CompanionException('磁盘空间不足，设置未保存。');
    if (clearKey) keyConfigured = false;
    if (apiKey?.isNotEmpty == true) keyConfigured = true;
    return super.saveSettings(settings);
  }

  @override
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text, {
    List<String> imageIds = const [],
    String? quoteId,
  }) {
    sends++;
    if (sendFailure != null) {
      return Stream.error(CompanionException(sendFailure!));
    }
    return super.send(
      conversation,
      request,
      text,
      imageIds: imageIds,
      quoteId: quoteId,
    );
  }
}

Future<SetupRepository> setup({
  String mode = 'api',
  bool consent = true,
}) async {
  final repository = SetupRepository();
  await repository.saveSettings({
    ...(await repository.bootstrap()).settings,
    'model_mode': mode,
    'storage_consent': consent,
    'model_consent': consent,
  });
  return repository;
}

String input(WidgetTester tester) => tester
    .widget<TextField>(find.byKey(const Key('message-input')))
    .controller!
    .text;

void main() {
  testWidgets(
    'startup failure is shown once and dismissal permits connection recovery',
    (tester) async {
      final repo = await setup(mode: 'offline');
      repo.failBootstrap = true;
      final c = CompanionController(repository: repo);
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      final popup = find.byKey(const Key('problem-dialog'));
      expect(popup, findsOneWidget);
      expect(
        find.descendant(of: popup, matching: find.text('本机引擎启动失败，请重新连接。')),
        findsOneWidget,
      );
      await tester.tap(find.byKey(const Key('dismiss-problem')));
      await tester.pumpAndSettle();
      repo.failBootstrap = false;
      await c.initialize();
      await tester.pumpAndSettle();
      expect(c.connected, isTrue);
      expect(c.error, isNull);
      expect(popup, findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );
  testWidgets(
    'missing key reminds without navigating or losing a quoted draft; settings is opt-in',
    (tester) async {
      final repo = await setup();
      final c = CompanionController(repository: repo);
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      final previous = c.messages.length;
      c.quoteMessage(c.messages.last);
      final quote = c.pendingQuote!.id;
      await tester.enterText(find.byKey(const Key('message-input')), '这条话先保留');
      await tester.pump();
      await tester.tap(find.byKey(const Key('send-message')));
      await tester.pumpAndSettle();
      expect(find.text('还没有配置 API Key'), findsOneWidget);
      expect(find.byType(SettingsSheet), findsNothing);
      expect(c.collecting, isFalse);
      expect(repo.sends, 0);
      expect(c.messages, hasLength(previous));
      expect(input(tester), '这条话先保留');
      expect(c.pendingQuote!.id, quote);
      // Concurrent failures update one dialog; they do not stack routes.
      await c.submit('这条话先保留');
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('problem-dialog')), findsOneWidget);
      await tester.tap(find.byKey(const Key('dismiss-problem')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('problem-dialog')), findsNothing);
      await tester.tap(find.byKey(const Key('message-input')));
      await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
      await tester.pumpAndSettle();
      expect(find.text('还没有配置 API Key'), findsOneWidget);
      expect(find.byType(SettingsSheet), findsNothing);
      await tester.tap(find.byKey(const Key('problem-settings')));
      await tester.pumpAndSettle();
      expect(find.byType(SettingsSheet), findsOneWidget);
      expect(find.text('回复方式'), findsOneWidget);
      expect(find.widgetWithText(TextFormField, 'API Key'), findsOneWidget);
      await tester.tap(find.byTooltip('关闭设置'));
      await tester.pumpAndSettle();
      expect(input(tester), '这条话先保留');
      expect(c.pendingQuote!.id, quote);
      expect(repo.sends, 0);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'first launch explains missing consent without blaming a key or opening settings',
    (tester) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      tester.view.viewInsets = const FakeViewPadding(bottom: 200);
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      addTearDown(tester.view.resetViewInsets);
      final repo = await setup(mode: 'offline', consent: false);
      final c = CompanionController(repository: repo);
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('message-input')), '第一次聊天');
      await tester.pump();
      await tester.tap(find.byKey(const Key('send-message')));
      await tester.pumpAndSettle();
      expect(find.text('还需要确认聊天选项'), findsOneWidget);
      expect(find.text('还没有配置 API Key'), findsNothing);
      expect(find.byType(SettingsSheet), findsNothing);
      expect(input(tester), '第一次聊天');
      expect(repo.sends, 0);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'saving a configured key dismisses notice and sends the preserved draft only on request',
    (tester) async {
      final repo = await setup();
      final c = CompanionController(repository: repo);
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('message-input')), '配置好再发');
      await tester.pump();
      await tester.tap(find.byKey(const Key('send-message')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('problem-settings')));
      await tester.pumpAndSettle();
      final keyField = find.widgetWithText(TextFormField, 'API Key');
      await tester.ensureVisible(keyField);
      await tester.enterText(keyField, 'synthetic-test-value-not-a-credential');
      await tester.tap(find.text('保存设置'));
      await tester.pumpAndSettle();
      expect(find.byType(SettingsSheet), findsNothing);
      expect(find.byKey(const Key('problem-dialog')), findsNothing);
      expect(input(tester), '配置好再发');
      expect(repo.sends, 0);
      await tester.tap(find.byKey(const Key('send-message')));
      await tester.pump(const Duration(milliseconds: 1250));
      for (var i = 0; i < 60; i++) {
        await tester.pump(const Duration(milliseconds: 40));
      }
      expect(repo.sends, 1);
      expect(
        c.messages.where((m) => m.isUser && m.text == '配置好再发'),
        hasLength(1),
      );
      expect(input(tester), isEmpty);
      expect(c.error, isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'offline text works without a key; image notice never forces navigation',
    (tester) async {
      final repo = await setup(mode: 'offline');
      final c = CompanionController(repository: repo);
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('message-input')), '离线聊一聊');
      await tester.tap(find.byKey(const Key('attach-image')));
      await tester.pumpAndSettle();
      expect(find.text('当前回复方式不能识图'), findsOneWidget);
      expect(find.byType(SettingsSheet), findsNothing);
      expect(input(tester), '离线聊一聊');
      await tester.tap(find.byKey(const Key('dismiss-problem')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('send-message')));
      await tester.pump(const Duration(milliseconds: 1250));
      for (var i = 0; i < 60; i++) {
        await tester.pump(const Duration(milliseconds: 40));
      }
      expect(repo.keyConfigured, isFalse);
      expect(repo.sends, 1);
      expect(c.error, isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  test('controller preflight retains text, images and quote and makes no request when a key is missing', () async {
    final repo = await setup();
    final c = CompanionController(repository: repo);
    addTearDown(c.dispose);
    await c.initialize();
    final before = c.messages.length;
    c.pendingImages.add('synthetic-image');
    c.quoteMessage(c.messages.last);
    final quote = c.pendingQuote;
    c.updateComposer('原来的草稿');
    expect(await c.submit(c.composerText), isFalse);
    await c.send(c.composerText);
    expect(c.problem.value!.title, contains('API Key'));
    expect(c.pendingImages, ['synthetic-image']);
    expect(c.pendingQuote, same(quote));
    expect(c.composerText, '原来的草稿');
    expect(c.messages, hasLength(before));
    expect(c.collecting, isFalse);
    expect(repo.sends, 0);
    c.connected = false;
    expect(c.chatSetupIssue(), ChatSetupIssue.connection);
  });

  testWidgets(
    'save failure is explained above settings and retains edits for recovery',
    (tester) async {
      final repo = await setup(mode: 'offline');
      final c = CompanionController(repository: repo);
      addTearDown(c.dispose);
      await tester.pumpWidget(XinYuApp(controller: c));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-settings')));
      await tester.pumpAndSettle();
      final name = find.widgetWithText(TextFormField, '怎么称呼 TA');
      await tester.enterText(name, '未保存的称呼');
      repo.failSave = true;
      await tester.tap(find.text('保存设置'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('problem-dialog')), findsOneWidget);
      expect(find.text('设置操作未完成'), findsOneWidget);
      expect(
        find.descendant(
          of: find.byKey(const Key('problem-dialog')),
          matching: find.text('磁盘空间不足，设置未保存。'),
        ),
        findsOneWidget,
      );
      await tester.tap(find.byKey(const Key('dismiss-problem')));
      await tester.pumpAndSettle();
      expect(find.byType(SettingsSheet), findsOneWidget);
      expect(tester.widget<TextFormField>(name).controller!.text, '未保存的称呼');
      repo.failSave = false;
      await tester.tap(find.text('保存设置'));
      await tester.pumpAndSettle();
      expect(c.companionName, '未保存的称呼');
      expect(find.byKey(const Key('problem-dialog')), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );

  for (final reason in [
    'API Key 无效或已过期，请检查后重试。',
    '模型请求超时，请稍后重试。',
    '请求过于频繁，请稍后再试。',
  ]) {
    testWidgets(
      'failed reply explains $reason and preserves the attempted message',
      (tester) async {
        final repo = await setup()
          ..keyConfigured = true;
        repo.sendFailure = reason;
        final c = CompanionController(repository: repo);
        addTearDown(c.dispose);
        await tester.pumpWidget(XinYuApp(controller: c));
        await tester.pumpAndSettle();
        c.settings['natural_chat'] = false;
        await tester.enterText(
          find.byKey(const Key('message-input')),
          '保留发送失败的这句话',
        );
        await tester.pump();
        await tester.tap(find.byKey(const Key('send-message')));
        await tester.pumpAndSettle();
        final popup = find.byKey(const Key('problem-dialog'));
        expect(popup, findsOneWidget);
        expect(
          find.descendant(of: popup, matching: find.text(reason)),
          findsOneWidget,
        );
        expect(find.byType(SettingsSheet), findsNothing);
        expect(repo.sends, 1);
        expect(c.messages.where((m) => m.text == '保留发送失败的这句话'), hasLength(1));
        // A concurrent failure updates the current popup, without another modal.
        c.reportProblem('连接已恢复，可以稍后再次操作。');
        await tester.pumpAndSettle();
        expect(popup, findsOneWidget);
        expect(find.text('连接已恢复，可以稍后再次操作。'), findsOneWidget);
        await tester.tap(find.byKey(const Key('dismiss-problem')));
        await tester.pumpAndSettle();
        expect(popup, findsNothing);
        expect(repo.sends, 1);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
