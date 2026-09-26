import 'dart:typed_data';

// Ignore only sub-pixel layout noise when deciding whether to follow new replies.
const chatBottomTolerance = 2.0;

class ChatLine {
  const ChatLine({
    required this.id,
    required this.text,
    required this.isUser,
    this.imageIds = const [],
    this.sticker,
    this.sequence = 0,
    this.createdAt,
    this.quote,
    this.notice = false,
    this.bookmarked = false,
  });
  final String id;
  final List<String> imageIds;
  final String text;
  final bool isUser;
  final StickerItem? sticker;
  final int sequence;
  final DateTime? createdAt;
  final QuotedMessage? quote;
  final bool notice;
  final bool bookmarked;
  ChatLine withBookmark(bool saved) => ChatLine(
    id: id,
    text: text,
    isUser: isUser,
    imageIds: imageIds,
    sticker: sticker,
    sequence: sequence,
    createdAt: createdAt,
    quote: quote,
    notice: notice,
    bookmarked: saved,
  );
  factory ChatLine.fromJson(Map<String, dynamic> value) => ChatLine(
    id: value['id'] as String,
    text: value['content'] as String,
    isUser: value['role'] == 'user',
    imageIds: (value['image_ids'] as List? ?? []).cast<String>(),
    sticker: value['sticker'] is Map
        ? StickerItem.fromJson(
            Map<String, dynamic>.from(value['sticker'] as Map),
          )
        : null,
    sequence: value['sequence'] as int? ?? 0,
    createdAt: DateTime.tryParse(value['created_at'] as String? ?? ''),
    quote: value['quote'] is Map
        ? QuotedMessage.fromJson(
            Map<String, dynamic>.from(value['quote'] as Map),
          )
        : null,
    notice: value['notice'] == true,
    bookmarked: value['bookmarked'] == true,
  );
}

class QuotedMessage {
  const QuotedMessage(this.id, this.text, this.isUser, {this.available = true});
  final String id, text;
  final bool isUser, available;
  factory QuotedMessage.fromJson(Map<String, dynamic> value) => QuotedMessage(
    value['id'] as String,
    value['content'] as String,
    value['role'] == 'user',
    available: value['available'] == true,
  );
}

class Conversation {
  const Conversation(this.id, this.title, {this.unread = 0});
  final String id;
  final String title;
  final int unread;
  factory Conversation.fromJson(Map<String, dynamic> value) => Conversation(
    value['id'] as String,
    value['title'] as String,
    unread: value['unread'] as int? ?? 0,
  );
}

class StickerItem {
  const StickerItem(this.id, this.label, this.kind);
  final String id, label, kind;
  factory StickerItem.fromJson(Map<String, dynamic> value) => StickerItem(
    value['id'] as String,
    value['label'] as String,
    value['kind'] as String,
  );
}

class SearchHit {
  const SearchHit(this.message, this.conversation, this.title, this.excerpt);
  final ChatLine message;
  final String conversation, title;
  final String excerpt;
  factory SearchHit.fromJson(Map<String, dynamic> value) => SearchHit(
    ChatLine.fromJson(Map<String, dynamic>.from(value['message'] as Map)),
    value['conversation_id'] as String,
    value['title'] as String,
    value['excerpt'] as String? ??
        (value['message'] as Map)['content'] as String,
  );
}

class Snapshot {
  const Snapshot(
    this.settings,
    this.conversations, {
    this.capabilities = const {},
  });
  final Map<String, dynamic> settings;
  final List<Conversation> conversations;
  final Map<String, dynamic> capabilities;
}

class MessagePage {
  const MessagePage(this.messages, {this.hasMore = false, this.before});
  final List<ChatLine> messages;
  final bool hasMore;
  final int? before;
}

abstract class CompanionRepository {
  bool get isDemo;
  Future<Snapshot> bootstrap();
  Future<Conversation> createConversation();
  Future<MessagePage> messages(String conversation, {int? before});
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text, {
    List<String> imageIds = const [],
    String? quoteId,
  });
  Future<Map<String, dynamic>> saveSettings(
    Map<String, dynamic> settings, {
    String? apiKey,
    bool? rememberKey,
    bool clearKey = false,
  });
  Future<String> uploadImage(Uint8List bytes, String purpose) =>
      throw const CompanionException('当前连接不支持图片。');
  Future<Uint8List> image(String id) =>
      throw const CompanionException('图片不可用。');
  Future<void> discardImage(String id) async {}
  Future<Map<String, dynamic>> readChatState(String conversation) async => {};
  Future<void> saveChatState(
    String conversation,
    Map<String, dynamic> state,
  ) async {}
  Future<void> bookmark(List<String> ids, bool saved) async =>
      throw const CompanionException('当前连接不支持收藏。');
  Future<Map<String, dynamic>> bookmarks({int offset = 0}) async => {
    'items': [],
    'has_more': false,
  };
  void close();
}

class CompanionException implements Exception {
  const CompanionException(this.message);
  final String message;
  @override
  String toString() => message;
}
