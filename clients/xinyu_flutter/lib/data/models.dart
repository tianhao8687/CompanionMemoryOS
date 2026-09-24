class ChatLine {
  const ChatLine({required this.id, required this.text, required this.isUser});
  final String id;
  final String text;
  final bool isUser;
  factory ChatLine.fromJson(Map<String, dynamic> value) => ChatLine(
    id: value['id'] as String,
    text: value['content'] as String,
    isUser: value['role'] == 'user',
  );
}

class Conversation {
  const Conversation(this.id, this.title);
  final String id;
  final String title;
  factory Conversation.fromJson(Map<String, dynamic> value) =>
      Conversation(value['id'] as String, value['title'] as String);
}

class Snapshot {
  const Snapshot(this.settings, this.conversations);
  final Map<String, dynamic> settings;
  final List<Conversation> conversations;
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
    String text,
  );
  Future<Map<String, dynamic>> saveSettings(
    Map<String, dynamic> settings, {
    String? apiKey,
  });
  void close();
}

class CompanionException implements Exception {
  const CompanionException(this.message);
  final String message;
  @override
  String toString() => message;
}
