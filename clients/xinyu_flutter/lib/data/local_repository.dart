import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'models.dart';

/// Existing loopback cookie handshake; no remote exposure or persisted secrets.
class LocalRepository implements CompanionRepository {
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
    String text,
  ) async* {
    final response = await _request('POST', '/api/chat/stream', {
      'conversation_id': conversation,
      'request_id': request,
      'content': text,
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

  Future<Map<String, dynamic>> memories(String conversation) =>
      _json('GET', '/api/memories/${Uri.encodeComponent(conversation)}');

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
