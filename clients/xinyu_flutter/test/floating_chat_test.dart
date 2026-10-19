import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/demo_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/state/floating_chat.dart';
import 'package:xinyu_flutter/ui/chat.dart';
import 'package:xinyu_flutter/ui/floating_chat_sheet.dart';

class FloatingRepository extends DemoRepository {
  final requests = <(String, String, String)>[];
  final screens = <Map<String, dynamic>?>[];
  final events = StreamController<Map<String, dynamic>>.broadcast();
  @override
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text, {
    List<String> imageIds = const [],
    String? quoteId,
    Map<String, dynamic>? screenContext,
  }) {
    requests.add((conversation, request, text));
    screens.add(screenContext);
    return events.stream;
  }

  void complete() {
    events.add({
      'type': 'result',
      'result': {
        'user': {
          'id': 'saved-user',
          'content': requests.last.$3,
          'role': 'user',
        },
        'assistant': {
          'id': 'saved-reply',
          'content': '我在，慢慢说。',
          'role': 'assistant',
        },
      },
    });
    events.close();
  }
}

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  const channel = MethodChannel('xinyu/floating-chat');
  const codec = StandardMethodCodec();
  late CompanionController controller;
  late FloatingChat floating;
  late FloatingRepository repository;
  final calls = <MethodCall>[];
  bool nativeRunning = false;
  bool screenReading = true;

  Future<dynamic> native(String method, [Map<String, dynamic>? args]) async {
    final completer = Completer<dynamic>();
    binding.defaultBinaryMessenger.handlePlatformMessage(
      channel.name,
      codec.encodeMethodCall(MethodCall(method, args)),
      (data) {
        try {
          completer.complete(data == null ? null : codec.decodeEnvelope(data));
        } catch (e) {
          completer.completeError(e);
        }
      },
    );
    return completer.future;
  }

  setUp(() {
    calls.clear();
    nativeRunning = false;
    screenReading = true;
    binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, (
      call,
    ) async {
      calls.add(call);
      if (call.method == 'start') nativeRunning = true;
      if (call.method == 'stop') nativeRunning = false;
      if (call.method == 'screen_mode') screenReading = call.arguments == true;
      if (['status', 'start', 'screen_mode'].contains(call.method)) {
        return {
          'supported': true,
          'permitted': true,
          'running': nativeRunning,
          'readScreen': screenReading,
        };
      }
      return null;
    });
  });
  Future<void> prepare() async {
    repository = FloatingRepository();
    controller = CompanionController(repository: repository);
    floating = FloatingChat(controller);
    await controller.initialize();
    controller.settings['natural_chat'] = false;
    await floating.initialize();
  }

  tearDown(() {
    floating.dispose();
    controller.dispose();
    if (!repository.events.isClosed) repository.events.close();
    binding.defaultBinaryMessenger.setMockMethodCallHandler(channel, null);
  });

  const screen = {
    'package_name': 'synthetic.chat',
    'app_name': '合成聊天',
    'text': '朋友：今天想安静一会。',
  };
  testWidgets(
    'opening reads once, replies in the original chat and preserves unsent input',
    (tester) async {
      await prepare();
      await floating.start();
      controller.updateComposer('还没发送的草稿');
      controller.pendingImages.add('unsent-image');
      expect(
        await native('screen_open', {
          'conversation': controller.active,
          'screen': screen,
        }),
        true,
      );
      expect(repository.requests.single.$3, '陪我看看当前屏幕。');
      expect(repository.screens.single, screen);
      expect(controller.composerText, '还没发送的草稿');
      expect(controller.pendingImages, ['unsent-image']);
      await native('screen_open', {
        'conversation': controller.active,
        'screen': screen,
      });
      expect(repository.requests.length, 1);
      repository.complete();
      await tester.pump(const Duration(milliseconds: 100));
      await native('screen_open', {
        'conversation': controller.active,
        'screen': screen,
      });
      expect(repository.requests.length, 1);
      expect(controller.messages.last.id, 'saved-reply');
      await tester.pump(const Duration(milliseconds: 350));
    },
  );

  testWidgets(
    'screen failure retry uses the same request and original evidence',
    (tester) async {
      await prepare();
      await floating.start();
      await native('screen_open', {
        'conversation': controller.active,
        'screen': screen,
      });
      repository.events.addError(const CompanionException('合成读屏回复失败'));
      await tester.pump(const Duration(milliseconds: 100));
      await native('retry', {'conversation': controller.active});
      expect(repository.requests.length, 2);
      expect(repository.requests.first.$2, repository.requests.last.$2);
      expect(repository.screens, [screen, screen]);
      repository.complete();
      await tester.pump(const Duration(milliseconds: 100));
    },
  );

  test(
    'unavailable, disabled and stale screen reads do not invent a conversation',
    () async {
      await prepare();
      await floating.start();
      await native('screen_open', {
        'conversation': controller.active,
        'notice': '当前页面读不到。',
      });
      expect(floating.snapshot()['notice'], '当前页面读不到。');
      expect(repository.requests, isEmpty);
      expect(
        await native('screen_open', {
          'conversation': 'old-conversation',
          'screen': screen,
        }),
        false,
      );
      await floating.setReadScreen(false);
      expect(
        await native('screen_open', {
          'conversation': controller.active,
          'screen': screen,
        }),
        false,
      );
      expect(repository.requests, isEmpty);
      expect(floating.snapshot()['readScreen'], false);
    },
  );

  testWidgets(
    'native send shares conversation, stream and final IDs with full chat',
    (tester) async {
      await prepare();
      await floating.start();
      controller.setForeground(false);
      expect(
        await native('send', {
          'conversation': controller.active,
          'text': '合成小窗消息',
          'editId': 1,
        }),
        true,
      );
      expect(repository.requests.single.$1, controller.active);
      expect(controller.messages.last.text, '合成小窗消息');
      expect(controller.composerText, '');
      expect(
        await native('send', {
          'conversation': controller.active,
          'text': '重复点击',
          'editId': 2,
        }),
        false,
      );
      repository.events.add({'type': 'delta', 'text': '我在'});
      await tester.pump(const Duration(milliseconds: 100));
      expect(floating.snapshot()['draft'], '我在');
      expect(repository.requests, hasLength(1));
      repository.complete();
      await tester.pump(const Duration(milliseconds: 100));
      expect(controller.messages.last.id, 'saved-reply');
      expect(
        controller.messages.where((m) => m.text == '合成小窗消息'),
        hasLength(1),
      );
      expect(
        (floating.snapshot()['messages'] as List).last['id'],
        'saved-reply',
      );
      controller.setForeground(true);
      expect(controller.messages.last.text, '我在，慢慢说。');
      await tester.pump(const Duration(milliseconds: 350));
    },
  );

  testWidgets(
    'composer synchronizes both directions without a second draft store',
    (tester) async {
      await prepare();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: Composer(controller: controller)),
        ),
      );
      await floating.start();
      controller.updateComposer('主界面草稿');
      await tester.pump(const Duration(milliseconds: 80));
      expect(
        (calls.lastWhere((c) => c.method == 'update').arguments
            as Map)['composer'],
        '主界面草稿',
      );
      expect(
        await native('edit', {
          'conversation': controller.active,
          'text': '小窗继续写',
          'editId': 3,
        }),
        true,
      );
      await tester.pump();
      expect(find.text('小窗继续写'), findsOneWidget);
      await native('closed');
      expect(controller.composerText, '小窗继续写');
      expect(floating.running, false);
      await tester.pumpWidget(const SizedBox());
    },
    timeout: const Timeout(Duration(seconds: 30)),
  );

  test('conversation switch rejects stale edits and sends', () async {
    await prepare();
    await floating.start();
    final old = controller.active;
    await controller.newConversation();
    expect(
      await native('send', {'conversation': old, 'text': '旧小窗', 'editId': 1}),
      false,
    );
    expect(
      await native('edit', {'conversation': old, 'text': '旧草稿', 'editId': 2}),
      false,
    );
    expect(controller.composerText, isEmpty);
    expect(repository.requests, isEmpty);
    expect(floating.snapshot()['conversation'], controller.active);
  });

  test('old draft acknowledgements and oversized input cannot replace current draft', () async {
    await prepare();
    await floating.start();
    final id = controller.active;
    await native('edit', {'conversation': id, 'text': '新的草稿', 'editId': 8});
    expect(
      await native('edit', {'conversation': id, 'text': '过期', 'editId': 7}),
      false,
    );
    expect(
      await native('edit', {
        'conversation': id,
        'text': '字' * 6001,
        'editId': 9,
      }),
      false,
    );
    expect(controller.composerText, '新的草稿');
  });

  test(
    'hidden attachments are not accidentally sent from the small window',
    () async {
      await prepare();
      await floating.start();
      controller.pendingImages.add('synthetic-image');
      expect(floating.snapshot()['canSend'], false);
      expect(
        await native('send', {
          'conversation': controller.active,
          'text': '只想发文字',
          'editId': 1,
        }),
        false,
      );
      expect(controller.pendingImages, ['synthetic-image']);
      expect(repository.requests, isEmpty);
    },
  );

  testWidgets('failure stays visible and retry uses the original request ID', (
    tester,
  ) async {
    await prepare();
    await floating.start();
    await native('send', {
      'conversation': controller.active,
      'text': '失败保留',
      'editId': 1,
    });
    repository.events.addError(const CompanionException('合成连接失败'));
    await tester.pump(const Duration(milliseconds: 100));
    expect(controller.canRetry, true);
    expect(floating.snapshot()['notice'], '合成连接失败');
    final original = repository.requests.single.$2;
    await native('retry', {'conversation': controller.active});
    await tester.pump(const Duration(milliseconds: 100));
    expect(repository.requests.last.$2, original);
    repository.complete();
    await tester.pump(const Duration(milliseconds: 100));
    expect(controller.canRetry, false);
    expect(controller.messages.last.id, 'saved-reply');
  });

  for (final width in [320.0, 768.0, 1024.0, 1440.0]) {
    testWidgets('small window entry is usable at width $width', (tester) async {
      await prepare();
      await tester.binding.setSurfaceSize(Size(width, 900));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: FloatingChatSheet(chat: floating)),
        ),
      );
      expect(find.text('开启小窗'), findsOneWidget);
      expect(find.byTooltip('关闭'), findsOneWidget);
      expect(tester.takeException(), isNull);
      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      await tester.pump();
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
}
