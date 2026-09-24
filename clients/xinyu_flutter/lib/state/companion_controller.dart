import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';

import '../data/demo_repository.dart';
import '../data/local_repository.dart';
import '../data/models.dart';

class CompanionController extends ChangeNotifier {
  CompanionController({CompanionRepository? repository})
    : _repository = repository ?? DemoRepository();
  CompanionRepository _repository;
  List<Conversation> conversations = [];
  List<ChatLine> messages = [];
  Map<String, dynamic> settings = {};
  String? active;
  bool loading = false, sending = false, hasMore = false;
  int? _before;
  String draft = '', status = '';
  String? error;
  String endpoint = const String.fromEnvironment(
    'COMPANION_URL',
    defaultValue: 'http://127.0.0.1:8766',
  );
  (String, String)? _failed;
  Timer? _paintTimer;
  bool _disposed = false;
  bool get isDemo => _repository.isDemo;
  bool get busy => loading || sending;
  bool get canRetry => _failed != null && !busy;
  String get companionName => settings['companion_name'] as String? ?? '小禾';
  String get userName => settings['user_name'] as String? ?? '';
  bool get ready =>
      isDemo ||
      (settings['storage_consent'] == true &&
          settings['model_consent'] == true);
  void _emit() {
    if (!_disposed) notifyListeners();
  }

  Map<String, dynamic> settingsCopy() =>
      jsonDecode(jsonEncode(settings)) as Map<String, dynamic>;
  Future<void> initialize() => _replace(_repository);

  Future<void> _replace(CompanionRepository next) async {
    if (busy) {
      if (!identical(next, _repository)) next.close();
      return;
    }
    loading = true;
    error = null;
    _emit();
    try {
      final snapshot = await next.bootstrap();
      final selected = snapshot.conversations.firstOrNull;
      final page = selected == null
          ? const MessagePage([])
          : await next.messages(selected.id);
      if (_disposed) {
        next.close();
        return;
      }
      if (!identical(next, _repository)) _repository.close();
      _repository = next;
      settings = snapshot.settings;
      conversations = snapshot.conversations;
      active = selected?.id;
      messages = page.messages;
      hasMore = page.hasMore;
      _before = page.before;
      _failed = null;
      draft = '';
    } catch (e) {
      if (!identical(next, _repository)) next.close();
      error = _error(e);
      rethrow;
    } finally {
      loading = false;
      _emit();
    }
  }

  Future<void> connect(String url) async {
    await _replace(LocalRepository(url));
    if (!isDemo) endpoint = url;
  }

  Future<void> useDemo() => _replace(DemoRepository());

  Future<void> select(String id) async {
    if (busy || id == active) return;
    loading = true;
    error = null;
    _emit();
    try {
      final page = await _repository.messages(id);
      active = id;
      messages = page.messages;
      hasMore = page.hasMore;
      _before = page.before;
      _failed = null;
      draft = '';
    } catch (e) {
      error = _error(e);
    } finally {
      loading = false;
      _emit();
    }
  }

  Future<void> newConversation() async {
    if (busy) return;
    loading = true;
    error = null;
    _emit();
    try {
      final item = await _repository.createConversation();
      conversations = [item, ...conversations];
      active = item.id;
      messages = [];
      hasMore = false;
      _before = null;
      _failed = null;
      draft = '';
    } catch (e) {
      error = _error(e);
    } finally {
      loading = false;
      _emit();
    }
  }

  Future<void> loadOlder() async {
    if (busy || !hasMore || active == null || _before == null) return;
    loading = true;
    error = null;
    _emit();
    try {
      final page = await _repository.messages(active!, before: _before);
      messages = [...page.messages, ...messages];
      hasMore = page.hasMore;
      _before = page.before;
    } catch (e) {
      error = _error(e);
    } finally {
      loading = false;
      _emit();
    }
  }

  Future<void> save(Map<String, dynamic> values, {String? apiKey}) async {
    if (busy) throw const CompanionException('请等当前操作完成后保存。');
    loading = true;
    _emit();
    try {
      settings = await _repository.saveSettings(values, apiKey: apiKey);
    } finally {
      loading = false;
      _emit();
    }
  }

  Future<void> send(String text) async {
    final content = text.trim();
    if (busy || content.isEmpty) return;
    if (!ready) {
      error = '请先在设置中确认对话保存与模型调用选项。';
      _emit();
      return;
    }
    if (content.length > 6000) {
      error = '每条消息最多 6000 字。';
      _emit();
      return;
    }
    if (active == null) await newConversation();
    if (active == null || _disposed) return;
    final random = Random.secure();
    final request =
        '${DateTime.now().microsecondsSinceEpoch}-${List.generate(8, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join()}';
    messages = [
      ...messages,
      ChatLine(id: request, text: content, isUser: true),
    ];
    await _send(content, request);
  }

  Future<void> retry() async {
    final failed = _failed;
    if (failed != null && !busy) await _send(failed.$1, failed.$2);
  }

  Future<void> _send(String text, String request) async {
    sending = true;
    error = null;
    draft = '';
    status = '正在认真听';
    _failed = null;
    _emit();
    var completed = false;
    try {
      await for (final event in _repository.send(active!, request, text)) {
        if (_disposed) break;
        switch (event['type']) {
          case 'delta':
            draft += event['text'] as String;
            _paintTimer ??= Timer(const Duration(milliseconds: 32), () {
              _paintTimer = null;
              _emit();
            });
          case 'reset':
            draft = '';
            _emit();
          case 'status':
            status = event['message'] as String? ?? status;
            _emit();
          case 'result':
            final result = event['result'] as Map<String, dynamic>;
            completed = true;
            final user = ChatLine.fromJson(
              Map<String, dynamic>.from(result['user'] as Map),
            );
            final assistant = ChatLine.fromJson(
              Map<String, dynamic>.from(result['assistant'] as Map),
            );
            messages = [
              ...messages.where(
                (m) =>
                    m.id != request && m.id != user.id && m.id != assistant.id,
              ),
              user,
              assistant,
            ];
            conversations = conversations
                .map(
                  (c) => c.id == active && c.title == '新的对话'
                      ? Conversation(
                          c.id,
                          text.substring(0, min(24, text.length)),
                        )
                      : c,
                )
                .toList();
            draft = '';
        }
      }
    } catch (e) {
      if (!completed) {
        error = _error(e);
        _failed = (text, request);
      }
    } finally {
      _paintTimer?.cancel();
      _paintTimer = null;
      sending = false;
      draft = '';
      _emit();
    }
  }

  Future<void> benchmark() async {
    if (!isDemo || busy) return;
    final demo = _repository as DemoRepository;
    final conversation = demo.addBenchmark();
    conversations = (await demo.bootstrap()).conversations;
    await select(conversation.id);
  }

  String _error(Object e) =>
      e is CompanionException ? e.message : '操作未完成，请检查本地服务后重试。';
  @override
  void dispose() {
    _disposed = true;
    _paintTimer?.cancel();
    _repository.close();
    super.dispose();
  }
}
