import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'models.dart';

/// Existing loopback cookie handshake; no remote exposure or persisted secrets.
class LocalRepository extends CompanionRepository {
  LocalRepository(String endpoint, {this.clientToken})
    : base = validateEndpoint(endpoint);
  final Uri base;
  final String? clientToken;
  final HttpClient _client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 4);
  Cookie? _session;

  static Uri validateEndpoint(String text) {
    final uri = Uri.tryParse(text.trim());
    if (uri == null ||
        uri.scheme != 'http' ||
        !{'127.0.0.1', 'localhost', '::1'}.contains(uri.host) ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        (uri.path.isNotEmpty && uri.path != '/')) {
      throw const CompanionException('本地版仅接受当前设备的回环地址。');
    }
    return uri.replace(path: '/');
  }

  @override
  bool get isDemo => false;

  Future<HttpClientResponse> _request(
    String method,
    String path, [
    Object? body,
  ]) async {
    try {
      final request = await _client.openUrl(method, base.resolve(path));
      request.followRedirects = false;
      request.headers.set('X-Companion-Client', 'local-web');
      if (clientToken != null) {
        request.headers.set('X-Xinyu-Token', clientToken!);
      }
      if (_session != null) request.cookies.add(_session!);
      if (body != null) {
        if (body is Uint8List) {
          request.headers.contentType = ContentType.binary;
          request.add(body);
        } else {
          request.headers.contentType = ContentType.json;
          request.write(jsonEncode(body));
        }
      }
      final response = await request.close().timeout(
        const Duration(seconds: 150),
      );
      if (response.statusCode < 200 || response.statusCode >= 300) {
        final content = await utf8.decoder.bind(response).join();
        String? detail;
        try {
          detail =
              (jsonDecode(content) as Map)['detail']?['message'] as String?;
        } catch (_) {
          /* Non-JSON errors. */
        }
        throw CompanionException(
          response.statusCode == 401
              ? '本地服务已重启，请在设置中重新连接。'
              : detail ?? '服务请求失败（${response.statusCode}）。',
        );
      }
      return response;
    } on SocketException {
      throw const CompanionException('本机记忆引擎连接中断，请重新连接或重启应用。');
    } on TimeoutException {
      throw const CompanionException('服务响应超时。消息已保留，可稍后重试。');
    } on HttpException {
      throw const CompanionException('连接中断，请检查服务后重试。');
    }
  }

  Future<Map<String, dynamic>> _json(
    String method,
    String path, [
    Object? body,
  ]) async {
    final response = await _request(method, path, body);
    final text = await utf8.decoder
        .bind(response)
        .join()
        .timeout(const Duration(seconds: 150));
    return jsonDecode(text) as Map<String, dynamic>;
  }

  @override
  Future<Snapshot> bootstrap() async {
    final response = await _request('GET', '/');
    final cookies = response.cookies.where(
      (c) => c.name == 'companion_romance_session_${base.port}',
    );
    _session = cookies.isEmpty ? null : cookies.first;
    await response.drain<void>();
    if (_session == null) throw const CompanionException('这个地址不是心隅本地服务。');
    final result = await _json('GET', '/api/bootstrap');
    return Snapshot(
      Map<String, dynamic>.from(result['settings'] as Map),
      (result['conversations'] as List)
          .map(
            (v) => Conversation.fromJson(Map<String, dynamic>.from(v as Map)),
          )
          .toList(),
      capabilities: Map<String, dynamic>.from(result)
        ..remove('settings')
        ..remove('conversations'),
    );
  }

  @override
  Future<Conversation> createConversation() async =>
      Conversation.fromJson(await _json('POST', '/api/conversations', {}));

  @override
  Future<MessagePage> messages(String conversation, {int? before}) async {
    final query = before == null ? '?limit=60' : '?limit=60&before=$before';
    final result = await _json(
      'GET',
      '/api/conversations/${Uri.encodeComponent(conversation)}/messages$query',
    );
    final rows = (result['messages'] as List).cast<Map<String, dynamic>>();
    return MessagePage(
      rows.map(ChatLine.fromJson).toList(),
      hasMore: result['has_more'] == true,
      before: rows.isEmpty ? null : rows.first['sequence'] as int?,
    );
  }

  @override
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text, {
    List<String> imageIds = const [],
    String? quoteId,
  }) async* {
    final response = await _request('POST', '/api/chat/stream', {
      'conversation_id': conversation,
      'request_id': request,
      'content': text,
      'image_ids': imageIds,
      'quote_id': quoteId,
    });
    var complete = false;
    await for (final line
        in response
            .transform(utf8.decoder)
            .transform(const LineSplitter())
            .timeout(const Duration(seconds: 150))) {
      if (line.trim().isEmpty) continue;
      final event = jsonDecode(line) as Map<String, dynamic>;
      if (event['type'] == 'error') {
        throw CompanionException(event['message'] as String);
      }
      if (event['type'] == 'result') complete = true;
      yield event;
    }
    if (!complete) throw const CompanionException('回复中断，未完成内容没有保存。可以重试这条消息。');
  }

  @override
  Future<Map<String, dynamic>> saveSettings(
    Map<String, dynamic> settings, {
    String? apiKey,
    bool? rememberKey,
    bool clearKey = false,
  }) async {
    final result = await _json('PUT', '/api/settings', {
      'settings': settings,
      if (apiKey != null && apiKey.trim().isNotEmpty) 'api_key': apiKey.trim(),
      'remember_api_key': ?rememberKey,
      'clear_api_key': clearKey,
    });
    return Map<String, dynamic>.from(result['settings'] as Map);
  }

  @override
  Future<String> uploadImage(Uint8List bytes, String purpose) async =>
      (await _json(
            'POST',
            '/api/images?purpose=${Uri.encodeQueryComponent(purpose)}',
            bytes,
          ))['id']
          as String;
  @override
  Future<Uint8List> image(String id) async {
    final response = await _request(
      'GET',
      '/api/images/${Uri.encodeComponent(id)}',
    );
    final bytes = BytesBuilder(copy: false);
    await for (final chunk in response) {
      bytes.add(chunk);
      if (bytes.length > 8 * 1024 * 1024) {
        throw const CompanionException('图片太大。');
      }
    }
    return bytes.takeBytes();
  }

  @override
  Future<void> discardImage(String id) async {
    await _json('DELETE', '/api/images/${Uri.encodeComponent(id)}');
  }

  Future<Map<String, dynamic>> memories(String conversation) =>
      _json('GET', '/api/memories/${Uri.encodeComponent(conversation)}');

  @override
  Future<Map<String, dynamic>> readChatState(String conversation) => _json(
    'GET',
    '/api/conversations/${Uri.encodeComponent(conversation)}/ui-state',
  );
  @override
  Future<void> saveChatState(
    String conversation,
    Map<String, dynamic> state,
  ) async {
    await _json(
      'PUT',
      '/api/conversations/${Uri.encodeComponent(conversation)}/ui-state',
      state,
    );
  }

  @override
  Future<void> bookmark(List<String> ids, bool saved) async {
    await _json('PUT', '/api/bookmarks', {'ids': ids, 'saved': saved});
  }

  @override
  Future<Map<String, dynamic>> bookmarks({int offset = 0}) =>
      _json('GET', '/api/bookmarks?offset=$offset');

  Future<Map<String, dynamic>> journal({
    bool moments = false,
    String category = 'all',
    int offset = 0,
  }) => _json(
    'GET',
    Uri(
      path: '/api/journal/entries',
      queryParameters: {
        'moments': '$moments',
        'category': category,
        'offset': '$offset',
      },
    ).toString(),
  );
  Future<Map<String, dynamic>> journalFlags(
    String id,
    String category,
    bool important,
  ) => _json('PUT', '/api/journal/entries/${Uri.encodeComponent(id)}/flags', {
    'category': category,
    'important': important,
  });
  Future<Map<String, dynamic>> saveMoment(Map<String, dynamic> value) =>
      _json('POST', '/api/journal/moments', value);
  Future<List<Map<String, dynamic>>> journalEvents() async =>
      ((await _json('GET', '/api/journal/events'))['items'] as List)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList();
  Future<Map<String, dynamic>> saveJournalEvent(
    Map<String, dynamic> value, {
    String? id,
  }) => _json(
    id == null ? 'POST' : 'PUT',
    id == null
        ? '/api/journal/events'
        : '/api/journal/events/${Uri.encodeComponent(id)}',
    value,
  );
  Future<void> closeJournalEvent(String id, String status) async {
    await _json('PUT', '/api/events/${Uri.encodeComponent(id)}', {
      'status': status,
    });
  }

  Future<Map<String, dynamic>> search(
    String query, {
    String? conversation,
    int? before,
  }) => _json(
    'GET',
    Uri(
      path: '/api/search',
      queryParameters: {
        'query': query,
        'conversation_id': ?conversation,
        if (before != null) 'before': '$before',
      },
    ).toString(),
  );
  Future<List<ChatLine>> context(String conversation, String id) async {
    final result = await _json(
      'GET',
      '/api/conversations/${Uri.encodeComponent(conversation)}/context/${Uri.encodeComponent(id)}',
    );
    return (result['messages'] as List)
        .map((v) => ChatLine.fromJson(Map<String, dynamic>.from(v as Map)))
        .toList();
  }

  Future<List<StickerItem>> stickers() async {
    final result = await _json('GET', '/api/stickers');
    return (result['stickers'] as List)
        .map((v) => StickerItem.fromJson(Map<String, dynamic>.from(v as Map)))
        .toList();
  }

  Future<StickerItem> uploadSticker(Uint8List bytes, String label) async =>
      StickerItem.fromJson(
        await _json(
          'POST',
          Uri(
            path: '/api/stickers',
            queryParameters: {'label': label},
          ).toString(),
          bytes,
        ),
      );
  Future<void> deleteSticker(String id) async {
    await _json('DELETE', '/api/stickers/${Uri.encodeComponent(id)}');
  }

  Future<Uint8List> stickerImage(String id) async {
    final response = await _request(
      'GET',
      '/api/stickers/${Uri.encodeComponent(id)}/content',
    );
    final bytes = BytesBuilder(copy: false);
    await for (final chunk in response) {
      bytes.add(chunk);
      if (bytes.length > 2 * 1024 * 1024) {
        throw const CompanionException('表情包太大。');
      }
    }
    return bytes.takeBytes();
  }

  Future<Map<String, dynamic>> updates() => _json('GET', '/api/updates');
  Future<void> markRead(String conversation, int through) async {
    await _json(
      'POST',
      '/api/conversations/${Uri.encodeComponent(conversation)}/read?through=$through',
      {},
    );
  }

  Future<void> forgetMemory(String id) async {
    await _json('POST', '/api/memories/${Uri.encodeComponent(id)}/forget', {});
  }

  Future<void> editMemory(
    String id,
    String content,
    String conversation,
  ) async {
    await _json('PUT', '/api/memories/${Uri.encodeComponent(id)}', {
      'content': content,
      'conversation_id': conversation,
    });
  }

  Future<void> cancel(String request) async {
    await _json(
      'POST',
      '/api/automation/cancel/${Uri.encodeComponent(request)}',
      {},
    );
  }

  Future<Uint8List> backup() async {
    final response = await _request('GET', '/api/local/backup');
    final bytes = BytesBuilder(copy: false);
    await for (final chunk in response) {
      bytes.add(chunk);
      if (bytes.length > 64 * 1024 * 1024) {
        throw const CompanionException('备份超过当前版本支持的 64 MB。');
      }
    }
    return bytes.takeBytes();
  }

  Future<void> restore(Uint8List bytes) async {
    await _json('POST', '/api/local/restore', bytes);
  }

  @override
  void close() => _client.close(force: true);
}
