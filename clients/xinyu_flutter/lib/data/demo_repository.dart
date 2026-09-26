import 'dart:typed_data';
import 'dart:async';

import 'models.dart';

const demoPairs = [
  ('今天终于有空，想坐下来慢慢聊一会儿。', '那就把这一小段时间留给自己吧。窗外是什么天气？'),
  ('有一点阳光，刚好落在桌子边上。', '很适合把杯子挪过去，连水都像变暖了一点。'),
  ('忙了一整天，脑子还没停下来。', '先不急着整理。想到哪儿就说到哪儿，我在这里。'),
  ('其实也没发生什么大事，只是有点累。', '小事堆在一起，也会很重。今天到这里，已经很好了。'),
  ('我想给自己留一点没有安排的时间。', '那我们就慢一点。听首歌，发一会儿呆，也算认真过今天。'),
];

class DemoRepository extends CompanionRepository {
  DemoRepository() {
    _history['demo'] = sampleMessages(10);
  }
  final List<Conversation> _conversations = [
    const Conversation('demo', '给今天留一点空白'),
  ];
  final Map<String, List<ChatLine>> _history = {};
  final _images = <String, Uint8List>{};
  final _ui = <String, Map<String, dynamic>>{};
  final _bookmarks = <String>{};
  String? _lastConversation;
  @override
  Future<Map<String, dynamic>> readChatState(String conversation) async =>
      Map.of(_ui[conversation] ?? {});
  @override
  Future<void> saveChatState(
    String conversation,
    Map<String, dynamic> state,
  ) async {
    _ui[conversation] = Map.of(state);
    if (state['is_current'] == true) _lastConversation = conversation;
  }

  @override
  Future<void> bookmark(List<String> ids, bool saved) async {
    if (saved) {
      _bookmarks.addAll(ids);
    } else {
      _bookmarks.removeAll(ids);
    }
  }

  @override
  Future<Map<String, dynamic>> bookmarks({int offset = 0}) async => {
    'items': [
      for (final entry in _history.entries)
        for (final m in entry.value)
          if (_bookmarks.contains(m.id))
            {
              'conversation_id': entry.key,
              'title': _conversations
                  .firstWhere((c) => c.id == entry.key)
                  .title,
              'message': {
                'id': m.id,
                'content': m.text,
                'role': m.isUser ? 'user' : 'assistant',
                'image_ids': m.imageIds,
                'bookmarked': true,
                'sequence': m.sequence,
              },
            },
    ],
    'has_more': false,
  };
  @override
  Future<String> uploadImage(Uint8List bytes, String purpose) async {
    final id = 'demo-image-${_images.length}';
    _images[id] = bytes;
    return id;
  }

  @override
  Future<Uint8List> image(String id) async =>
      _images[id] ?? (throw const CompanionException('图片不可用。'));
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
      sequence: i + 1,
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
  Future<Snapshot> bootstrap() async => Snapshot(
    Map.of(_settings),
    List.of(_conversations),
    capabilities: {
      'chat_experience': true,
      'last_conversation': _lastConversation,
    },
  );
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
      MessagePage([
        for (final m in _history[conversation] ?? <ChatLine>[])
          m.withBookmark(_bookmarks.contains(m.id)),
      ]);
  @override
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text, {
    List<String> imageIds = const [],
    String? quoteId,
  }) async* {
    final history = _history[conversation]!;
    final user = ChatLine(
      id: request,
      text: text,
      isUser: true,
      imageIds: imageIds,
      sequence: history.length + 1,
    );
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
      sequence: history.length + 2,
    );
    history.addAll([user, assistant]);
    yield {
      'type': 'result',
      'result': {
        'user': {
          'id': user.id,
          'content': user.text,
          'role': 'user',
          'image_ids': imageIds,
          'sequence': user.sequence,
        },
        'assistant': {
          'id': assistant.id,
          'content': assistant.text,
          'role': 'assistant',
          'sequence': assistant.sequence,
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
  Future<void> discardImage(String id) async {
    _images.remove(id);
  }

  @override
  void close() {}
}
