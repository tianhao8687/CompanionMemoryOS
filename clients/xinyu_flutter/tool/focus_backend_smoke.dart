import 'dart:convert';
import 'dart:io';

import 'package:xinyu_flutter/data/local_repository.dart';

/// Only run against a fresh ManagedInstance with synthetic data.
Future<void> main(List<String> args) async {
  if (args.length != 1) {
    throw ArgumentError('Pass the isolated test service URL.');
  }
  final repo = LocalRepository(args.single);
  try {
    final initial = await repo.bootstrap();
    if (initial.capabilities['focus_features'] != true) {
      throw StateError('The engine does not advertise focus support.');
    }
    final conversation = await repo.createConversation();
    final id = 'flutter-focus-${DateTime.now().microsecondsSinceEpoch}';
    await repo
        .send(conversation.id, '$id-chat', '我得把商品资料整理一下，你陪我半小时。')
        .drain<void>();
    final messages = await repo.messages(conversation.id);
    final card = messages.messages.last.focusProposal;
    if (card?['focus_minutes'] != 30 || card?['intention'] != '整理商品资料') {
      throw StateError(
        'The native message decoder lost the editable proposal.',
      );
    }
    final payload = {
      'request_id': '$id-start',
      'conversation_id': conversation.id,
      'intention': card!['intention'],
      'focus_minutes': 30,
      'rest_minutes': 5,
    };
    final started = await repo.startFocus(payload);
    final session = started['session'] as Map;
    final replay = await repo.startFocus(payload);
    if ((replay['session'] as Map)['id'] != session['id']) {
      throw StateError('Duplicate start made a second clock.');
    }
    final paused = await repo.focusAction({
      'session_id': session['id'],
      'revision': session['revision'],
      'action': 'pause',
    });
    if ((paused['session'] as Map)['phase'] != 'focus_paused') {
      throw StateError('Pause failed.');
    }
    if (await repo.claimFocusNotice(
      session['id'] as String,
      (paused['session'] as Map)['revision'] as int,
    )) {
      throw StateError('A paused clock must not deliver a deadline notice.');
    }
    final reopened = LocalRepository(args.single);
    try {
      await reopened.bootstrap();
      final secondView = await reopened.focus(conversation.id);
      if ((secondView['session'] as Map)['id'] != session['id'] ||
          (secondView['session'] as Map)['phase'] != 'focus_paused') {
        throw StateError('A second native connection did not share the clock.');
      }
    } finally {
      reopened.close();
    }
    const question =
        '我刚才在做「整理商品资料」，现在有点卡住了。'
        '我选的小步骤是「把第一件商品的规格列出来」。陪我商量一下接下来先做什么吧。';
    await repo.send(conversation.id, '$id-discuss', question).drain<void>();
    final discussion = await repo.messages(conversation.id);
    if (discussion.messages
                .where((line) => line.isUser && line.text == question)
                .length !=
            1 ||
        discussion.messages.last.isUser ||
        discussion.messages.last.text.isEmpty) {
      throw StateError(
        'Focus discussion did not persist through ordinary chat.',
      );
    }
    final afterDiscussion =
        (await repo.focus(conversation.id))['session'] as Map;
    if (afterDiscussion['id'] != session['id'] ||
        afterDiscussion['phase'] != 'focus_paused') {
      throw StateError('Discussion unexpectedly changed the shared clock.');
    }
    stdout.writeln(
      jsonEncode({
        'status': 'passed',
        'session_id': session['id'],
        'conversation_id': conversation.id,
        'checks': [
          'native handshake',
          'streamed proposal decoding',
          'idempotent start',
          'pause',
          'native notice handshake',
          'shared native connections',
          'focus discussion stored in current conversation',
          'discussion preserves paused shared clock',
        ],
      }),
    );
  } finally {
    repo.close();
  }
}
