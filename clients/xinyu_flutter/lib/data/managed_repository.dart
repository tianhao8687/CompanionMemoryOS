import 'dart:typed_data';
import 'dart:async';

import 'local_repository.dart';
import 'models.dart';
import 'native_runtime.dart';

class ManagedRepository extends CompanionRepository {
  ManagedRepository({NativeRuntime? runtime})
    : runtime = runtime ?? NativeRuntime();
  final NativeRuntime runtime;
  LocalRepository? _repository;
  bool _closed = false;
  LocalRepository get connection =>
      _repository ?? (throw const CompanionException('本机引擎尚未就绪，请重新连接。'));
  @override
  bool get isDemo => false;
  @override
  Future<Snapshot> bootstrap() async {
    if (_closed) throw const CompanionException('应用已关闭。');
    final result = await runtime.start();
    if (_closed) {
      await runtime.stop();
      throw const CompanionException('应用已关闭。');
    }
    _repository?.close();
    _repository = LocalRepository(
      result['endpoint'] as String,
      clientToken: result['token'] as String,
    );
    return connection.bootstrap();
  }

  Future<void> restart() async {
    _repository?.close();
    _repository = null;
    await runtime.stop();
  }

  @override
  Future<Conversation> createConversation() => connection.createConversation();
  @override
  Future<MessagePage> messages(String conversation, {int? before}) =>
      connection.messages(conversation, before: before);
  @override
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text, {
    List<String> imageIds = const [],
    String? quoteId,
  }) => connection.send(
    conversation,
    request,
    text,
    imageIds: imageIds,
    quoteId: quoteId,
  );
  @override
  Future<Map<String, dynamic>> saveSettings(
    Map<String, dynamic> settings, {
    String? apiKey,
    bool? rememberKey,
    bool clearKey = false,
  }) => connection.saveSettings(
    settings,
    apiKey: apiKey,
    rememberKey: rememberKey,
    clearKey: clearKey,
  );
  @override
  Future<String> uploadImage(Uint8List bytes, String purpose) =>
      connection.uploadImage(bytes, purpose);
  @override
  Future<Uint8List> image(String id) => connection.image(id);
  @override
  Future<void> discardImage(String id) => connection.discardImage(id);
  @override
  Future<Map<String, dynamic>> readChatState(String conversation) =>
      connection.readChatState(conversation);
  @override
  Future<void> saveChatState(String conversation, Map<String, dynamic> state) =>
      connection.saveChatState(conversation, state);
  @override
  Future<void> bookmark(List<String> ids, bool saved) =>
      connection.bookmark(ids, saved);
  @override
  Future<Map<String, dynamic>> bookmarks({int offset = 0}) =>
      connection.bookmarks(offset: offset);
  @override
  void close() {
    _closed = true;
    _repository?.close();
    unawaited(runtime.stop().catchError((Object _) {}));
  }
}
