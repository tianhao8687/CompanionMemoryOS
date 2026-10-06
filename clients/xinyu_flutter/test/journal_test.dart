import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/local_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';
import 'package:xinyu_flutter/ui/chat.dart';
import 'package:xinyu_flutter/ui/journal_sheet.dart';

class JournalRepository extends LocalRepository {
  JournalRepository() : super('http://127.0.0.1:12345');
  String? quoted;
  Map<String, dynamic>? savedMoment, savedEvent;
  bool important = false;
  final entry = <String, dynamic>{
    'id': 'memory1',
    'title': '海边的晚霞',
    'content': '我们聊起了那天的海。',
    'category': 'together',
    'important': false,
    'reality_layer': 'real_world',
    'happened_on': '2026-09-20',
    'image_ids': <String>[],
    'sources': <Map<String, dynamic>>[],
  };
  @override
  Future<Snapshot> bootstrap() async => const Snapshot(
    {
      'model_mode': 'offline',
      'storage_consent': true,
      'model_consent': true,
      'companion_name': '小禾',
      'calendar_timezone': 'Asia/Shanghai',
    },
    [Conversation('chat', '看海')],
    capabilities: {'model_ready': true, 'journal_features': true},
  );
  @override
  Future<MessagePage> messages(String conversation, {int? before}) async =>
      const MessagePage([
        ChatLine(id: 'source', text: '下次一起看海吧', isUser: false, sequence: 1),
      ]);
  @override
  Future<Map<String, dynamic>> journal({
    bool moments = false,
    String category = 'all',
    int offset = 0,
  }) async => {
    'items': [
      {...entry, 'important': important},
    ],
    'has_more': false,
    'offset': 40,
  };
  @override
  Future<Map<String, dynamic>> journalFlags(
    String id,
    String category,
    bool value,
  ) async {
    important = value;
    return {...entry, 'important': value};
  }

  @override
  Future<List<Map<String, dynamic>>> journalEvents() async => [];
  @override
  Future<Map<String, dynamic>> saveMoment(Map<String, dynamic> value) async {
    savedMoment = value;
    return entry;
  }

  @override
  Future<Map<String, dynamic>> saveJournalEvent(
    Map<String, dynamic> value, {
    String? id,
  }) async {
    savedEvent = value;
    return value;
  }

  @override
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text, {
    List<String> imageIds = const [],
    String? quoteId,
  }) async* {
    quoted = quoteId;
    yield {
      'type': 'result',
      'result': {
        'user': {
          'id': 'user',
          'content': text,
          'role': 'user',
          'sequence': 2,
          'quote': {
            'id': quoteId,
            'content': '下次一起看海吧',
            'role': 'assistant',
            'available': true,
          },
        },
        'assistant': {
          'id': 'reply',
          'content': '好呀',
          'role': 'assistant',
          'sequence': 3,
        },
      },
    };
  }
}

void main() {
  testWidgets(
    'small screen with large text keeps complete tab labels reachable',
    (tester) async {
      tester.view.physicalSize = const Size(320, 640);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final controller = CompanionController(repository: JournalRepository());
      await controller.initialize();
      await tester.pumpWidget(
        MaterialApp(
          builder: (context, child) => MediaQuery(
            data: MediaQuery.of(context)
                .copyWith(textScaler: const TextScaler.linear(1.24)),
            child: child!,
          ),
          home: Scaffold(body: JournalSheet(controller: controller)),
        ),
      );
      await tester.pumpAndSettle();
      for (final label in ['记忆', '纪念与约定', '共同回忆']) {
        final target = find.text(label).first;
        expect(target.hitTestable(), findsOneWidget);
        expect(
          tester.getSize(target).height,
          lessThan(32),
          reason: 'tab label stays on one line',
        );
        await tester.tap(target);
        await tester.pumpAndSettle();
      }
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  testWidgets('journal tabs, important flag and narrow layout', (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final repository = JournalRepository();
    final controller = CompanionController(repository: repository);
    await controller.initialize();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: JournalSheet(controller: controller)),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('我们的手账'), findsOneWidget);
    expect(find.text('海边的晚霞'), findsOneWidget);
    await tester.tap(find.byTooltip('标记重要'));
    await tester.pumpAndSettle();
    expect(repository.important, isTrue);
    await tester.tap(find.text('纪念与约定'));
    await tester.pumpAndSettle();
    expect(find.text('记下日期或约定'), findsOneWidget);
    await tester.tap(find.text('共同回忆'));
    await tester.pumpAndSettle();
    expect(find.text('留下一段回忆'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  testWidgets('quote action reaches composer and backend and can be removed', (
    tester,
  ) async {
    final repository = JournalRepository();
    final controller = CompanionController(repository: repository);
    await controller.initialize();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ListenableBuilder(
            listenable: controller,
            builder: (_, _) => Column(
              children: [
                Expanded(child: ConversationView(controller: controller)),
                Composer(controller: controller),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.longPress(find.text('下次一起看海吧'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('引用回复'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('quote-preview')), findsOneWidget);
    await tester.enterText(find.byKey(const Key('message-input')), '我们周末去');
    await tester.pump();
    await tester.tap(find.byKey(const Key('send-message')));
    await tester.pumpAndSettle();
    expect(repository.quoted, 'source');
    expect(find.byKey(const Key('quote-preview')), findsNothing);
    expect(find.byKey(const ValueKey('quote-user')), findsOneWidget);
    controller.quoteMessage(controller.messages.first);
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('cancel-quote')));
    await tester.pumpAndSettle();
    expect(controller.pendingQuote, isNull);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });

  testWidgets(
    'save shared moment keeps explicit story flag and selected source',
    (tester) async {
      final repository = JournalRepository();
      final controller = CompanionController(repository: repository);
      await controller.initialize();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Builder(
              builder: (context) => TextButton(
                onPressed: () => saveChatMoment(
                  context,
                  controller,
                  controller.messages.first,
                ),
                child: const Text('打开'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('打开'));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('moment-title')), '月亮上的约定');
      await tester.tap(find.text('这是故事里的经历'));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('save-moment')));
      await tester.tap(find.byKey(const Key('save-moment')));
      await tester.pumpAndSettle();
      expect(repository.savedMoment?['source_ids'], ['source']);
      expect(repository.savedMoment?['reality_layer'], 'roleplay');
      expect(repository.savedMoment?['title'], '月亮上的约定');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
      controller.dispose();
    },
  );

  testWidgets('anniversary defaults to yearly and model-free reminders', (
    tester,
  ) async {
    final repository = JournalRepository();
    final controller = CompanionController(repository: repository);
    await controller.initialize();
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => TextButton(
              onPressed: () => showDialog<bool>(
                context: context,
                builder: (_) => JournalEventEditor(controller: controller),
              ),
              child: const Text('打开'),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('纪念日'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('event-title')), '相识纪念日');
    await tester.ensureVisible(find.byKey(const Key('save-event')));
    await tester.tap(find.byKey(const Key('save-event')));
    await tester.pumpAndSettle();
    expect(repository.savedEvent?['yearly'], true);
    expect(repository.savedEvent?['mode'], 'reminder');
    expect(repository.savedEvent?['kind'], 'anniversary');
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox());
    controller.dispose();
  });
}
