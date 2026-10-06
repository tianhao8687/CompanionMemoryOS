import 'dart:async';
import 'dart:convert';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/image_import.dart';
import 'package:xinyu_flutter/data/local_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/main.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/stickers.dart';

class FeatureFixture extends LocalRepository {
  FeatureFixture() : super('http://127.0.0.1:1');
  Map<String, dynamic> values = {
    'companion_name': '小禾',
    'style': 'gentle',
    'model_mode': 'api',
    'storage_consent': true,
    'model_consent': true,
    'proactive_enabled': false,
    'quiet_start': 22,
    'quiet_end': 8,
    'stickers_enabled': true,
    'deepseek': {'model': 'synthetic', 'base_url': 'https://example.com'},
  };
  final calls = <(String, String?, int?)>[];
  final stale = Completer<Map<String, dynamic>>();
  final readThrough = <int>[];
  var unread = false;
  @override
  Future<Snapshot> bootstrap() async => Snapshot(
    values,
    [const Conversation('chat', '画画的日子')],
    capabilities: {
      'chat_features': true,
      'key_persisted': true,
      'model_ready': true,
    },
  );
  @override
  Future<MessagePage> messages(String conversation, {int? before}) async =>
      MessagePage([
        const ChatLine(id: 'user', text: '今天画画了', isUser: true, sequence: 1),
        const ChatLine(
          id: 'reply',
          text: '给你加油',
          isUser: false,
          sequence: 2,
          sticker: StickerItem('builtin_cheer', '加油', 'builtin'),
        ),
        if (unread)
          const ChatLine(
            id: 'outreach',
            text: '想起你那幅画了',
            isUser: false,
            sequence: 3,
          ),
      ], before: 1);
  @override
  Future<Map<String, dynamic>> updates() async => {
    'conversations': [
      {'id': 'chat', 'title': '画画的日子', 'unread': unread ? 1 : 0},
    ],
    'outreach': {'status': 'sent'},
    'proactive_enabled': values['proactive_enabled'],
    'notification_conversations': unread ? ['chat'] : <String>[],
  };
  @override
  Future<void> markRead(String conversation, int through) async {
    readThrough.add(through);
  }

  @override
  Future<Map<String, dynamic>> saveSettings(
    Map<String, dynamic> settings, {
    String? apiKey,
    bool? rememberKey,
    bool clearKey = false,
  }) async {
    values = settings;
    return values;
  }

  @override
  Future<Map<String, dynamic>> search(
    String query, {
    String? conversation,
    int? before,
  }) async {
    calls.add((query, conversation, before));
    if (query == '旧') return stale.future;
    return {
      'results': [
        {
          'message': {
            'id': 'hit',
            'content': '我也喜欢海边',
            'role': 'assistant',
            'sequence': 2,
          },
          'conversation_id': 'chat',
          'title': '画画的日子',
          'excerpt': '我也喜欢海边',
        },
      ],
      'has_more': before == null,
      'before': 2,
    };
  }

  @override
  Future<List<ChatLine>> context(String conversation, String id) async => [
    const ChatLine(id: 'before', text: '记得我们的海边吗', isUser: true),
    const ChatLine(id: 'hit', text: '我也喜欢海边', isUser: false),
  ];
  @override
  Future<List<StickerItem>> stickers() async => [
    for (final entry in {
      'hug': '抱抱',
      'happy': '开心',
      'miss_you': '想你了',
      'cheer': '加油',
      'shy': '害羞',
      'sleepy': '晚安',
      'sad': '委屈',
      'surprise': '惊讶',
    }.entries)
      StickerItem('builtin_${entry.key}', entry.value, 'builtin'),
  ];
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final nativeCalls = <MethodCall>[];
  setUp(() {
    nativeCalls.clear();
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(const MethodChannel('xinyu/notifications'), (
          call,
        ) async {
          nativeCalls.add(call);
          if (call.method == 'status') {
            return {'supported': true, 'allowed': true};
          }
          if (call.method == 'test') return true;
          return null;
        });
  });
  tearDown(
    () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(
          const MethodChannel('xinyu/notifications'),
          null,
        ),
  );

  testWidgets(
    'Search discards stale results, scopes, paginates and opens context',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final repository = FeatureFixture();
      final controller = CompanionController(repository: repository);
      await tester.pumpWidget(XinYuApp(controller: controller));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('open-search')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('chat-search-input')), '旧');
      await tester.pump(const Duration(milliseconds: 400));
      await tester.enterText(find.byKey(const Key('chat-search-input')), '海边');
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pumpAndSettle();
      repository.stale.complete({'results': [], 'has_more': false});
      await tester.pumpAndSettle();
      expect(find.text('我也喜欢海边'), findsOneWidget);
      expect(repository.calls.last.$2, 'chat');
      await tester.tap(find.text('全部对话'));
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pumpAndSettle();
      expect(repository.calls.last.$2, isNull);
      await tester.tap(find.text('更多结果'));
      await tester.pumpAndSettle();
      expect(repository.calls.last.$3, 2);
      await tester.tap(find.text('我也喜欢海边').first);
      await tester.pumpAndSettle();
      expect(find.text('记得我们的海边吗'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
    },
  );

  testWidgets(
    'Message settings and all illustrated stickers fit a narrow phone',
    (tester) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final repository = FeatureFixture();
      final controller = CompanionController(repository: repository);
      await tester.pumpWidget(XinYuApp(controller: controller));
      await tester.pumpAndSettle();
      expect(find.byType(StickerView), findsOneWidget);
      await tester.tap(find.byKey(const Key('open-settings')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('消息'));
      await tester.pumpAndSettle();
      await Scrollable.ensureVisible(
        tester.element(find.text('内置表情与我的表情包')),
        alignment: .5,
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('内置表情与我的表情包'));
      await tester.pumpAndSettle();
      expect(find.text('我们的表情包'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(find.byTooltip('关闭表情库'));
      await tester.pumpAndSettle();
      final scrollable = find
          .descendant(
            of: find.byKey(const Key('settings-scroll')),
            matching: find.byType(Scrollable),
          )
          .first;
      await tester.scrollUntilVisible(
        find.text('允许主动联系'),
        150,
        scrollable: scrollable,
      );
      await tester.tap(find.text('允许主动联系'));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('免打扰时间'),
        160,
        scrollable: scrollable,
      );
      expect(find.text('22:00'), findsOneWidget);
      expect(find.text('08:00'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.tap(find.text('保存设置'));
      await tester.pumpAndSettle();
      expect(repository.values['proactive_enabled'], true);
      expect(
        nativeCalls.any(
          (c) =>
              c.method == 'configure' &&
              (c.arguments as Map)['enabled'] == true,
        ),
        true,
      );
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
    },
  );

  testWidgets(
    'Foreground refresh delivers once and marks only displayed sequence read',
    (tester) async {
      final repository = FeatureFixture();
      final controller = CompanionController(repository: repository);
      await tester.pumpWidget(XinYuApp(controller: controller));
      await tester.pumpAndSettle();
      repository.unread = true;
      await controller.refreshUpdates();
      await controller.refreshUpdates();
      await tester.pumpAndSettle();
      expect(controller.messages.where((m) => m.id == 'outreach').length, 1);
      expect(repository.readThrough.last, 3);
      controller.setForeground(false);
      await tester.pump();
      expect(nativeCalls.last.arguments, {'conversation': null});
      await tester.pumpWidget(const SizedBox.shrink());
      controller.dispose();
    },
  );

  test('GIF imports retain all animation frames', () async {
    final one = base64Decode(
      'R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==',
    );
    final start = one.indexOf(0x2c);
    final animated = Uint8List.fromList([
      ...one.take(one.length - 1),
      ...one.sublist(start),
    ]);
    final result = await normalizeSticker(animated);
    expect(result, orderedEquals(animated));
    final codec = await ui.instantiateImageCodec(result);
    expect(codec.frameCount, 2);
    codec.dispose();
  });
}
