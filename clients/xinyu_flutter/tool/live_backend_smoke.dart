import 'dart:io';

import 'package:xinyu_flutter/data/local_repository.dart';

/// Run against a NEW disposable --data-dir, never the user's existing service.
Future<void> main(List<String> args) async {
  if (args.length != 1) {
    throw ArgumentError('Pass the disposable local test service URL.');
  }
  final repository = LocalRepository(args.single);
  final initial = await repository.bootstrap();
  try {
    final settings = Map<String, dynamic>.from(initial.settings)
      ..['model_mode'] = 'offline'
      ..['storage_consent'] = true
      ..['model_consent'] = true;
    await repository.saveSettings(settings);
    final conversation = await repository.createConversation();
    final request = 'flutter-smoke-${DateTime.now().microsecondsSinceEpoch}';
    final events = await repository
        .send(conversation.id, request, '这是客户端联调测试，我喜欢桂花茶。')
        .toList();
    if (!events.any((e) => e['type'] == 'result')) {
      throw StateError('Missing completed reply.');
    }
    final messages = await repository.messages(conversation.id);
    if (messages.messages.length != 2 || !messages.messages.first.isUser) {
      throw StateError('Unexpected persisted conversation.');
    }
    await repository
        .send(conversation.id, request, '这是客户端联调测试，我喜欢桂花茶。')
        .drain<void>();
    if ((await repository.messages(conversation.id)).messages.length != 2) {
      throw StateError('Retry created duplicate messages.');
    }
    stdout.writeln(
      'PASS: handshake, settings, streaming, persisted history, idempotent replay (offline model).',
    );
  } finally {
    await repository.saveSettings(initial.settings);
    repository.close();
  }
}
