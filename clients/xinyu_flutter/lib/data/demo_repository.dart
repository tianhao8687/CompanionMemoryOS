import 'dart:async';

import 'models.dart';

const demoPairs = [
  ('今天终于有空，想坐下来慢慢聊一会儿。', '那就把这一小段时间留给自己吧。窗外是什么天气？'),
  ('有一点阳光，刚好落在桌子边上。', '很适合把杯子挪过去，连水都像变暖了一点。'),
  ('忙了一整天，脑子还没停下来。', '先不急着整理。想到哪儿就说到哪儿，我在这里。'),
  ('其实也没发生什么大事，只是有点累。', '小事堆在一起，也会很重。今天到这里，已经很好了。'),
  ('我想给自己留一点没有安排的时间。', '那我们就慢一点。听首歌，发一会儿呆，也算认真过今天。'),
];

class DemoRepository implements CompanionRepository {
  DemoRepository() {
    _history['demo'] = sampleMessages(10);
  }
  final List<Conversation> _conversations = [
    const Conversation('demo', '给今天留一点空白'),
  ];
  final Map<String, List<ChatLine>> _history = {};
  Map<String, dynamic> _settings = {
    'companion_name': '小禾',
    'user_name': '',
    'style': 'gentle',
    'persona_notes': '',
    'model_mode': 'offline',
    'storage_consent': false,
    'model_consent': false,
    'romance_consent': false,
  };
  static List<ChatLine> sampleMessages(int count) => List.generate(count, (i) {
    final pair = demoPairs[(i ~/ 2) % demoPairs.length];
    return ChatLine(
      id: 'sample-$i',
      text: i.isEven ? pair.$1 : pair.$2,
      isUser: i.isEven,
    );
  });
  Conversation addBenchmark() {
    final id = 'bench-${DateTime.now().microsecondsSinceEpoch}';
    final conversation = Conversation(id, '长对话测试 · 200 条示例');
    _history[id] = sampleMessages(200);
    _conversations.insert(0, conversation);
    return conversation;
  }

  @override
  bool get isDemo => true;
  @override
  Future<Snapshot> bootstrap() async =>
      Snapshot(Map.of(_settings), List.of(_conversations));
  @override
  Future<Conversation> createConversation() async {
    final item = Conversation(
      'demo-${DateTime.now().microsecondsSinceEpoch}',
      '新的对话',
    );
    _conversations.insert(0, item);
    _history[item.id] = [];
    return item;
  }

  @override
  Future<MessagePage> messages(String conversation, {int? before}) async =>
      MessagePage(List.of(_history[conversation] ?? []));
  @override
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text,
  ) async* {
    final history = _history[conversation]!;
    final user = ChatLine(id: request, text: text, isUser: true);
    const reply =
        '我在，慢慢说就好。\n\n这是原型的示例回复，用来体验输入和玻璃界面。在设置中连接本地服务后，就能和真正的陪伴模型聊天。';
    yield {'type': 'status', 'message': '正在播放示例回复'};
    for (var i = 0; i < reply.length; i += 4) {
      await Future<void>.delayed(const Duration(milliseconds: 28));
      yield {
        'type': 'delta',
        'text': reply.substring(i, (i + 4).clamp(0, reply.length)),
      };
    }
    final assistant = ChatLine(
      id: '$request-reply',
      text: reply,
      isUser: false,
    );
    history.addAll([user, assistant]);
    yield {
      'type': 'result',
      'result': {
        'user': {'id': user.id, 'content': user.text, 'role': 'user'},
        'assistant': {
          'id': assistant.id,
          'content': assistant.text,
          'role': 'assistant',
        },
      },
    };
    yield {'type': 'done'};
  }

  @override
  Future<Map<String, dynamic>> saveSettings(
    Map<String, dynamic> settings, {
    String? apiKey,
    bool? rememberKey,
    bool clearKey = false,
  }) async {
    _settings = Map.of(settings);
    return Map.of(_settings);
  }

  @override
  void close() {}
}
