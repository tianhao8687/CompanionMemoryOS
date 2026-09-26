import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../data/demo_repository.dart';
import '../data/image_import.dart';
import '../data/local_repository.dart';
import '../data/managed_repository.dart';
import '../data/models.dart';
import '../data/chat_notifications.dart';
import '../data/user_problem.dart';

enum ChatSetupIssue {
  connection('本机引擎尚未连接', '请在连接与数据中重新连接，再发送消息。'),
  apiKey('还没有配置 API Key', '当前使用联网模型，请填写 API Key 后再发送。也可以选择离线规则回复体验聊天流程。'),
  consent('还需要确认聊天选项', '请在连接与数据中确认“允许保存对话与记忆”和“允许所选回复方式处理消息”。'),
  vision('当前回复方式不能识图', '请启用支持图片的联网模型，或移除图片后发送文字。');

  const ChatSetupIssue(this.title, this.message);
  final String title, message;
}

class CompanionController extends ChangeNotifier {
  CompanionController({CompanionRepository? repository})
    : _repository = repository ?? DemoRepository();
  CompanionRepository _repository;
  List<Conversation> conversations = [];
  List<ChatLine> messages = [];
  Map<String, dynamic> settings = {};
  Map<String, dynamic> capabilities = {};
  bool connected = false;
  String? _activeRequest;
  String? active;
  bool loading = false, sending = false, hasMore = false;
  int? _before;
  String draft = '', status = '';
  String? _lastError;
  final problem = ValueNotifier<UserProblem?>(null);
  String? get error => _lastError;
  set error(String? value) {
    _lastError = value;
    if (value != null) reportProblem(value);
  }

  void reportProblem(
    String message, {
    String title = '操作未完成',
    bool openSettings = false,
  }) {
    if (!_disposed) {
      problem.value = UserProblem(title, message, openSettings: openSettings);
    }
  }

  String reportFailure(
    Object cause, {
    String title = '操作未完成',
    String fallback = '操作未完成，暂时无法确定具体原因。请稍后再试。',
  }) {
    final message = userProblemMessage(cause, fallback: fallback);
    reportProblem(message, title: title);
    return message;
  }

  Future<bool> copyText(String text) async {
    try {
      await Clipboard.setData(ClipboardData(text: text));
      return true;
    } catch (e) {
      reportFailure(e, title: '文字未能复制');
      return false;
    }
  }

  bool get hasExperience => capabilities['chat_experience'] == true;
  bool get naturalChat => settings['natural_chat'] != false;
  String composerText = '';
  int composerRevision = 0;
  final _viewStates = <String, Map<String, dynamic>>{};
  Timer? _stateTimer, _collectTimer;
  Future<void> _stateWrite = Future.value();
  final selectedMessages = <String>{};
  bool selecting = false, collecting = false;
  String _collected = '';
  static const _queueId = 'local-collecting';
  bool atLatest = true;
  Map<String, dynamic> get viewState => Map.of(_viewStates[active] ?? {});

  void setReadingPosition(Map<String, dynamic> position) {
    final id = active;
    if (id == null) return;
    atLatest = (position['scroll_offset'] as num? ?? 0) <= chatBottomTolerance;
    _viewStates[id] = {...?_viewStates[id], ...position};
    _scheduleState();
  }

  void updateComposer(String value) {
    composerText = value;
    if (collecting && _collected.length + value.length + 2 > 6000) {
      // Send the already accepted group; keep the new text intact as its own draft.
      unawaited(sendCollected());
    }
    _rememberComposer();
    if (collecting) _scheduleCollected();
  }

  void _rememberComposer() {
    final id = active;
    if (id == null) return;
    _viewStates[id] = {
      ...?_viewStates[id],
      'text': [
        _collected,
        composerText,
      ].where((v) => v.isNotEmpty).join('\n\n'),
      'quote_id': pendingQuote?.id,
      'image_ids': List.of(pendingImages),
    };
    _scheduleState();
  }

  void _scheduleState() {
    _stateTimer?.cancel();
    _stateTimer = Timer(
      const Duration(milliseconds: 250),
      () => unawaited(flushChatState()),
    );
  }

  Future<void> flushChatState() {
    _stateTimer?.cancel();
    if (!hasExperience || (!isDemo && settings['storage_consent'] != true)) {
      return Future.value();
    }
    final repository = _repository;
    final snapshot = _viewStates.map(
      (k, v) => MapEntry(k, {...v, 'is_current': k == active}),
    );
    _stateWrite = _stateWrite
        .then((_) async {
          for (final entry in snapshot.entries) {
            await repository.saveChatState(entry.key, entry.value);
          }
        })
        .catchError((Object e) {
          if (!_disposed && identical(repository, _repository)) {
            error = '草稿或阅读位置保存未完成：${_error(e)}';
            _emit();
          }
        });
    return _stateWrite;
  }

  Future<void> _restoreChatState() async {
    final id = active;
    if (id == null) return;
    var saved = hasExperience
        ? await _repository.readChatState(id)
        : <String, dynamic>{};
    saved = Map<String, dynamic>.from(saved);
    _viewStates[id] = saved;
    composerText = saved['text'] as String? ?? '';
    composerRevision++;
    pendingImages
      ..clear()
      ..addAll((saved['image_ids'] as List? ?? []).cast<String>());
    pendingQuote = null;
    final quote = saved['quote_id'] as String?;
    final anchor = saved['anchor_id'] as String?;
    while (anchor != null &&
        !messages.any((m) => m.id == anchor) &&
        hasMore &&
        _before != null) {
      final page = await _repository.messages(id, before: _before);
      messages = [...page.messages, ...messages];
      hasMore = page.hasMore;
      _before = page.before;
    }
    if (quote != null) {
      var source = messages.where((m) => m.id == quote).firstOrNull;
      if (source == null && localConnection != null) {
        try {
          source = (await localConnection!.context(
            id,
            quote,
          )).where((m) => m.id == quote).firstOrNull;
        } catch (_) {
          /* Deleted quotes are not resurrected from a cached copy. */
        }
      }
      if (source != null) {
        pendingQuote = QuotedMessage(source.id, source.text, source.isUser);
      }
    }
    selectedMessages.clear();
    selecting = false;
    atLatest = (saved['scroll_offset'] as num? ?? 0) <= chatBottomTolerance;
  }

  void startSelection(ChatLine line) {
    selecting = true;
    selectedMessages
      ..clear()
      ..add(line.id);
    _emit();
  }

  void toggleSelection(String id) {
    if (!selectedMessages.remove(id) && selectedMessages.length < 100) {
      selectedMessages.add(id);
    }
    _emit();
  }

  void endSelection() {
    selecting = false;
    selectedMessages.clear();
    _emit();
  }

  Future<void> bookmarkMessages(List<String> ids, bool saved) async {
    await _repository.bookmark(ids, saved);
    messages = [
      for (final m in messages) ids.contains(m.id) ? m.withBookmark(saved) : m,
    ];
    _emit();
  }

  Future<Map<String, dynamic>> bookmarks({int offset = 0}) =>
      _repository.bookmarks(offset: offset);

  Future<bool> submit(String text) async {
    if (loading || sending || (text.trim().isEmpty && pendingImages.isEmpty)) {
      return false;
    }
    if (!checkChatSetup(withImages: pendingImages.isNotEmpty)) return false;
    if (text.trim().length + _collected.length + (_collected.isEmpty ? 0 : 2) >
        6000) {
      error = '这一组消息最多 6000 字，请等本轮发送后继续。';
      _emit();
      return false;
    }
    if (!naturalChat || pendingImages.isNotEmpty || pendingQuote != null) {
      if (collecting) return false;
      unawaited(send(text));
      return true;
    }
    if (active == null) await newConversation();
    if (active == null) return false;
    _collected = [
      _collected,
      text.trim(),
    ].where((v) => v.isNotEmpty).join('\n\n');
    collecting = true;
    error = null;
    messages = [
      ...messages.where((m) => m.id != _queueId),
      ChatLine(id: _queueId, text: _collected, isUser: true),
    ];
    outgoingRevision++;
    _scheduleCollected();
    _rememberComposer();
    _emit();
    return true;
  }

  void _scheduleCollected() {
    _collectTimer?.cancel();
    _collectTimer = Timer(
      const Duration(milliseconds: 1200),
      () => unawaited(sendCollected()),
    );
  }

  Future<void> sendCollected() async {
    if (!collecting || sending || loading) return;
    _collectTimer?.cancel();
    final content = _collected;
    collecting = false;
    _collected = '';
    messages = messages.where((m) => m.id != _queueId).toList();
    _rememberComposer();
    await send(content, followLatest: false);
  }

  void cancelCollected() {
    _collectTimer?.cancel();
    collecting = false;
    composerText = [
      _collected,
      composerText,
    ].where((s) => s.isNotEmpty).join('\n\n');
    _collected = '';
    composerRevision++;
    messages = messages.where((m) => m.id != _queueId).toList();
    _rememberComposer();
    _emit();
  }

  String endpoint = const String.fromEnvironment(
    'COMPANION_URL',
    defaultValue: 'http://127.0.0.1:8766',
  );
  (String, String, List<String>, QuotedMessage?)? _failed;
  QuotedMessage? pendingQuote;
  bool get hasJournal =>
      capabilities['journal_features'] == true && localConnection != null;
  void quoteMessage(ChatLine? line) {
    if (busy) return;
    pendingQuote = line == null
        ? null
        : QuotedMessage(line.id, line.text, line.isUser);
    _rememberComposer();
    _emit();
  }

  final pendingImages = <String>[];
  final _imageCache = <String, Future<Uint8List>>{};
  final _stickerCache = <String, Future<Uint8List>>{};
  final notifications = ChatNotifications();
  Timer? _updateTimer;
  bool _foreground = true, _polling = false;
  String? _notificationTarget;
  Map<String, dynamic> outreachState = {};
  bool get hasChatFeatures =>
      capabilities['chat_features'] == true && localConnection != null;

  Future<Uint8List> stickerImage(String id) {
    if (_stickerCache.length >= 8 && !_stickerCache.containsKey(id)) {
      _stickerCache.remove(_stickerCache.keys.first);
    }
    return _stickerCache.putIfAbsent(
      id,
      () => localConnection!.stickerImage(id),
    );
  }

  Future<void> deleteSticker(String id) async {
    await localConnection!.deleteSticker(id);
    _stickerCache.remove(id);
    messages = messages
        .map(
          (m) => m.sticker?.id == id
              ? ChatLine(
                  id: m.id,
                  text: m.text,
                  isUser: m.isUser,
                  imageIds: m.imageIds,
                  sequence: m.sequence,
                  createdAt: m.createdAt,
                  quote: m.quote,
                  notice: m.notice,
                  sticker: StickerItem(id, '表情包已删除', 'missing'),
                )
              : m,
        )
        .toList();
    _emit();
  }

  void setForeground(bool value) {
    _foreground = value;
    if (!value) unawaited(flushChatState());
    if (!hasChatFeatures) return;
    if (!value) {
      unawaited(notifications.call('visible', {'conversation': null}));
    } else {
      unawaited(refreshUpdates());
    }
  }

  Future<void> _openNotification(String id) async {
    if (id == 'test') return;
    _notificationTarget = id;
    await refreshUpdates();
  }

  Future<void> _startUpdates() async {
    _updateTimer?.cancel();
    if (!hasChatFeatures) return;
    notifications.listen(_openNotification);
    final initial = await notifications.call<String>('openedConversation');
    if (_disposed || !hasChatFeatures) return;
    if (initial != null && initial != 'test') _notificationTarget = initial;
    _updateTimer = Timer.periodic(
      const Duration(seconds: 15),
      (_) => unawaited(refreshUpdates()),
    );
    await _markVisible();
    await refreshUpdates();
  }

  Future<void> _markVisible() async {
    final id = active;
    if (!hasChatFeatures || !_foreground || id == null || _disposed) {
      return;
    }
    final through = messages.fold<int>(0, (n, m) => max(n, m.sequence));
    final connection = localConnection!;
    await notifications.call('visible', {'conversation': id});
    if (_disposed ||
        !_foreground ||
        active != id ||
        localConnection != connection) {
      return;
    }
    if (!atLatest) return;
    if (through > 0) await connection.markRead(id, through);
    await notifications.call('read', {'conversation': id});
    conversations = conversations
        .map((c) => c.id == id ? Conversation(c.id, c.title) : c)
        .toList();
  }

  Future<void> refreshUpdates() async {
    if (!hasChatFeatures || _disposed || !_foreground || busy || _polling) {
      return;
    }
    _polling = true;
    final connection = localConnection!;
    final selected = active;
    try {
      final update = await connection.updates();
      if (_disposed ||
          busy ||
          localConnection != connection ||
          active != selected) {
        return;
      }
      conversations = (update['conversations'] as List)
          .map(
            (v) => Conversation.fromJson(Map<String, dynamic>.from(v as Map)),
          )
          .toList();
      outreachState = Map<String, dynamic>.from(update['outreach'] as Map);
      settings['proactive_enabled'] = update['proactive_enabled'] == true;
      await notifications.call('configure', {
        'enabled':
            update['background_enabled'] == true ||
            settings['proactive_enabled'] == true,
      });
      await notifications.call('reconcile', {
        'valid': (update['notification_conversations'] as List).cast<String>(),
      });
      final target = _notificationTarget;
      if (target != null && conversations.any((c) => c.id == target)) {
        _notificationTarget = null;
        await select(target);
      }
      final id = active;
      if (id != null) {
        final page = await connection.messages(id);
        if (_disposed ||
            busy ||
            active != id ||
            localConnection != connection) {
          return;
        }
        final first = page.messages.firstOrNull?.sequence ?? 0;
        final existing = messages.where(
          (m) => m.sequence < first || m.sequence == 0,
        );
        messages = [...existing, ...page.messages];
        if (_before == null) {
          _before = page.before;
          hasMore = page.hasMore;
        }
        await _markVisible();
      }
      _emit();
    } catch (_) {
      // A periodic refresh never destroys an unsent message or replaces its error.
    } finally {
      _polling = false;
    }
  }

  int outgoingRevision = 0;
  bool get visionReady => isDemo || capabilities['vision_ready'] == true;
  Future<Uint8List> image(String id) {
    final cached = _imageCache[id];
    if (cached != null) return cached;
    if (_imageCache.length >= 8) _imageCache.remove(_imageCache.keys.first);
    return _imageCache[id] = _repository.image(id);
  }

  Future<String?> importImage(String purpose) async {
    if (busy) return null;
    loading = true;
    _emit();
    try {
      final bytes = await pickLocalImage(purpose);
      if (bytes == null || _disposed) return null;
      final id = await _repository.uploadImage(bytes, purpose);
      if (_imageCache.length >= 8) _imageCache.remove(_imageCache.keys.first);
      _imageCache[id] = Future.value(bytes);
      return id;
    } finally {
      loading = false;
      _emit();
    }
  }

  Future<void> attachImage() async {
    if (busy) return;
    if (!checkChatSetup(withImages: true)) return;
    if (pendingImages.length >= 4) {
      error = '每条消息最多 4 张图片。';
      _emit();
      return;
    }
    try {
      final id = await importImage('chat');
      if (id != null) pendingImages.add(id);
      _rememberComposer();
      error = null;
    } catch (e) {
      error = e is PlatformException ? e.message ?? '无法选择图片。' : _error(e);
    }
    _emit();
  }

  void removeImage(String id) {
    pendingImages.remove(id);
    _rememberComposer();
    discardImage(id);
    _emit();
  }

  void discardImage(String id) {
    _imageCache.remove(id);
    unawaited(_repository.discardImage(id).catchError((Object _) {}));
  }

  void _discardPending() {
    pendingQuote = null;
    for (final id in pendingImages) {
      discardImage(id);
    }
    pendingImages.clear();
  }

  Timer? _paintTimer;
  bool _disposed = false;
  bool get isDemo => _repository.isDemo;
  bool get busy => loading || sending || collecting;
  bool get canRetry => _failed != null && !busy;
  String get companionName => settings['companion_name'] as String? ?? '小禾';
  String get userName => settings['user_name'] as String? ?? '';
  ChatSetupIssue? chatSetupIssue({bool withImages = false}) {
    if (isDemo) return null;
    if (!connected) return ChatSetupIssue.connection;
    if (settings['model_mode'] == 'api' &&
        (capabilities['model_ready'] ?? capabilities['key_configured']) !=
            true) {
      return ChatSetupIssue.apiKey;
    }
    if (settings['storage_consent'] != true ||
        settings['model_consent'] != true) {
      return ChatSetupIssue.consent;
    }
    if (withImages && !visionReady) return ChatSetupIssue.vision;
    return null;
  }

  bool get ready => chatSetupIssue() == null;

  bool checkChatSetup({bool withImages = false}) {
    final issue = chatSetupIssue(withImages: withImages);
    if (issue == null) return true;
    _lastError = null;
    reportProblem(issue.message, title: issue.title, openSettings: true);
    _emit();
    return false;
  }

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
    await flushChatState();
    loading = true;
    error = null;
    _emit();
    try {
      final snapshot = await next.bootstrap();
      final selected =
          (identical(next, _repository)
              ? snapshot.conversations
                    .where((item) => item.id == active)
                    .firstOrNull
              : null) ??
          snapshot.conversations
              .where(
                (item) => item.id == snapshot.capabilities['last_conversation'],
              )
              .firstOrNull ??
          snapshot.conversations.firstOrNull;
      final page = selected == null
          ? const MessagePage([])
          : await next.messages(selected.id);
      if (_disposed) {
        next.close();
        return;
      }
      if (!identical(next, _repository)) _repository.close();
      _repository = next;
      _viewStates.clear();
      _imageCache.clear();
      _stickerCache.clear();
      pendingImages.clear();
      pendingQuote = null;
      settings = snapshot.settings;
      capabilities = snapshot.capabilities;
      connected = true;
      conversations = snapshot.conversations;
      active = selected?.id;
      messages = page.messages;
      hasMore = page.hasMore;
      _before = page.before;
      _failed = null;
      draft = '';
      _discardPending();
      await _restoreChatState();
      unawaited(_startUpdates().catchError((Object _) {}));
    } catch (e) {
      if (identical(next, _repository)) connected = false;
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

  Future<void> useLocal() async {
    if (_repository is ManagedRepository) {
      await _replace(_repository);
    } else {
      await _replace(ManagedRepository());
    }
  }

  LocalRepository? get localConnection => switch (_repository) {
    ManagedRepository repository => repository.connection,
    LocalRepository repository => repository,
    _ => null,
  };

  Future<void> cancel() async {
    final request = _activeRequest;
    if (request != null) await localConnection?.cancel(request);
  }

  Future<bool> backup() async {
    if (busy || _repository is! ManagedRepository) return false;
    loading = true;
    _emit();
    try {
      final bytes = await localConnection!.backup();
      return await const MethodChannel(
            'xinyu/local-files',
          ).invokeMethod<bool>('saveBackup', {
            'bytes': bytes,
            'name':
                'xinyu-${DateTime.now().toIso8601String().substring(0, 10)}.sqlite',
          }) ??
          false;
    } finally {
      loading = false;
      _emit();
    }
  }

  Future<bool> restoreBackup() async {
    if (busy || _repository is! ManagedRepository) return false;
    final repository = _repository as ManagedRepository;
    loading = true;
    _emit();
    var restored = false;
    try {
      final bytes = await const MethodChannel('xinyu/local-files')
          .invokeMethod<Uint8List>('pickBackup');
      if (bytes == null) return false;
      await repository.connection.restore(bytes);
      connected = false;
      await repository.restart();
      restored = true;
    } finally {
      loading = false;
      _emit();
    }
    if (restored) await _replace(repository);
    return restored;
  }

  bool get hasManagedStorage => _repository is ManagedRepository;

  Future<void> select(String id) async {
    if (busy || id == active) return;
    await flushChatState();
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
      await _restoreChatState();
      await _markVisible();
    } catch (e) {
      error = _error(e);
    } finally {
      loading = false;
      _emit();
    }
  }

  Future<void> newConversation({bool keepImages = false}) async {
    if (busy) return;
    await flushChatState();
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
      if (!keepImages) {
        pendingImages.clear();
        composerText = '';
        composerRevision++;
      }
      pendingQuote = null;
      selectedMessages.clear();
      selecting = false;
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

  Future<void> save(
    Map<String, dynamic> values, {
    String? apiKey,
    bool? rememberKey,
    bool clearKey = false,
  }) async {
    if (busy) throw const CompanionException('请等当前操作完成后保存。');
    loading = true;
    _emit();
    try {
      settings = await _repository.saveSettings(
        values,
        apiKey: apiKey,
        rememberKey: rememberKey,
        clearKey: clearKey,
      );
      final snapshot = await _repository.bootstrap();
      capabilities = snapshot.capabilities;
      if (!isDemo && settings['storage_consent'] != true) {
        _viewStates.clear();
        composerText = '';
        composerRevision++;
        _discardPending();
      }
      if (hasChatFeatures) {
        await notifications.call('configure', {
          'enabled':
              (values['proactive_enabled'] == true ||
                  capabilities['journal_background'] == true) &&
              values['storage_consent'] == true &&
              (values['model_consent'] == true ||
                  capabilities['journal_background'] == true),
        });
      }
    } finally {
      loading = false;
      _emit();
    }
  }

  Future<void> send(String text, {bool followLatest = true}) async {
    final content = text.trim();
    if (busy || (content.isEmpty && pendingImages.isEmpty)) return;
    if (!checkChatSetup(withImages: pendingImages.isNotEmpty)) return;
    if (content.length > 6000) {
      error = '每条消息最多 6000 字。';
      _emit();
      return;
    }
    if (active == null) await newConversation(keepImages: true);
    if (active == null || _disposed) return;
    final images = List<String>.of(pendingImages);
    final quoted = pendingQuote;
    pendingQuote = null;
    pendingImages.clear();
    _rememberComposer();
    if (followLatest) outgoingRevision++;
    final random = Random.secure();
    final request =
        '${DateTime.now().microsecondsSinceEpoch}-${List.generate(8, (_) => random.nextInt(256).toRadixString(16).padLeft(2, '0')).join()}';
    messages = [
      ...messages,
      ChatLine(
        id: request,
        text: content,
        isUser: true,
        imageIds: images,
        quote: quoted,
      ),
    ];
    await _send(content, request, images, quoted);
  }

  Future<void> retry() async {
    final failed = _failed;
    if (failed != null && !busy) {
      if (!checkChatSetup(withImages: failed.$3.isNotEmpty)) return;
      outgoingRevision++;
      await _send(failed.$1, failed.$2, failed.$3, failed.$4);
    }
  }

  Future<void> _send(
    String text,
    String request,
    List<String> images,
    QuotedMessage? quote,
  ) async {
    _activeRequest = request;
    sending = true;
    error = null;
    draft = '';
    status = '正在认真听';
    _failed = null;
    _emit();
    var completed = false;
    try {
      await for (final event in _repository.send(
        active!,
        request,
        text,
        imageIds: images,
        quoteId: quote?.id,
      )) {
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
                          text.isEmpty
                              ? '[图片]'
                              : text.substring(0, min(24, text.length)),
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
        _failed = (text, request, images, quote);
      }
    } finally {
      _paintTimer?.cancel();
      _paintTimer = null;
      sending = false;
      _activeRequest = null;
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

  String _error(Object e) => userProblemMessage(e);
  @override
  void dispose() {
    _disposed = true;
    _paintTimer?.cancel();
    _updateTimer?.cancel();
    _collectTimer?.cancel();
    _stateTimer?.cancel();
    notifications.dispose();
    problem.dispose();
    unawaited(flushChatState().whenComplete(_repository.close));
    super.dispose();
  }
}
