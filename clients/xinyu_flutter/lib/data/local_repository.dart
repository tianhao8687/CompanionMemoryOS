import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'models.dart';

/// Existing loopback cookie handshake; no remote exposure or persisted secrets.
class LocalRepository implements CompanionRepository {
  LocalRepository(String endpoint) : base = validateEndpoint(endpoint);
  final Uri base;
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
      throw const CompanionException(
        '原型仅连接本机服务，例如 http://127.0.0.1:8766。手机联调请使用 USB 端口转发。',
      );
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
      if (_session != null) request.cookies.add(_session!);
      if (body != null) {
        request.headers.contentType = ContentType.json;
        request.write(jsonEncode(body));
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
      throw const CompanionException('无法连接本地服务。请启动原型后端；手机请先配置 USB 端口转发。');
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
  }) async {
    final result = await _json('PUT', '/api/settings', {
      'settings': settings,
      if (apiKey != null && apiKey.trim().isNotEmpty) 'api_key': apiKey.trim(),
    });
    return Map<String, dynamic>.from(result['settings'] as Map);
  }

  @override
  void close() => _client.close(force: true);
}
