import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/demo_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

class RetryRepository extends DemoRepository {
  final requests = <String>[];
  final attachments = <List<String>>[];
  bool failAfterResult = false;
  @override
  Stream<Map<String, dynamic>> send(
    String conversation,
    String request,
    String text, {
    List<String> imageIds = const [],
    String? quoteId,
  }) async* {
    requests.add(request);
    attachments.add(List.of(imageIds));
    if (requests.length == 1 && !failAfterResult) {
      yield {'type': 'delta', 'text': '未完成'};
      throw const CompanionException('连接断开');
    }
    yield {
      'type': 'result',
      'result': {
        'user': {
          'id': 'saved-user',
          'content': text,
          'role': 'user',
          'image_ids': imageIds,
        },
        'assistant': {
          'id': 'saved-reply',
          'content': '已完成的回复',
          'role': 'assistant',
        },
      },
    };
    if (failAfterResult) throw const CompanionException('已提交后的连接断开');
  }
}

void main() {
  test('First image-only message keeps its attachment through conversation creation and retry', () async {
    final repo = RetryRepository();
    final controller = CompanionController(repository: repo);
    addTearDown(controller.dispose);
    await controller.initialize();
    controller.active = null;
    controller.pendingImages.add('synthetic-image');
    await controller.send('');
    expect(controller.canRetry, isTrue);
    expect(controller.messages.single.imageIds, ['synthetic-image']);
    await controller.retry();
    expect(repo.requests[0], repo.requests[1]);
    expect(repo.attachments, [
      ['synthetic-image'],
      ['synthetic-image'],
    ]);
    expect(controller.messages.first.imageIds, ['synthetic-image']);
    expect(controller.outgoingRevision, 2);
  });
  test('Retry reuses request id, discards partial answer and replaces optimistic row', () async {
    final repo = RetryRepository();
    final controller = CompanionController(repository: repo);
    addTearDown(controller.dispose);
    await controller.initialize();
    await controller.send('我的消息');
    expect(controller.error, '连接断开');
    expect(controller.draft, isEmpty);
    expect(controller.canRetry, isTrue);
    await controller.retry();
    expect(repo.requests[0], repo.requests[1]);
    expect(controller.messages.where((m) => m.text == '我的消息'), hasLength(1));
    expect(controller.messages.last.text, '已完成的回复');
    expect(controller.error, isNull);
  });

  test(
    'Committed result remains successful when trailing transport closes',
    () async {
      final controller = CompanionController(
        repository: RetryRepository()..failAfterResult = true,
      );
      addTearDown(controller.dispose);
      await controller.initialize();
      await controller.send('已保存');
      expect(controller.error, isNull);
      expect(controller.canRetry, isFalse);
      expect(controller.messages.last.text, '已完成的回复');
    },
  );

  test('Settings edits keep unknown nested backend fields', () async {
    final controller = CompanionController();
    addTearDown(controller.dispose);
    await controller.initialize();
    controller.settings['cognition'] = {
      'custom': {'value': 17},
    };
    final copy = controller.settingsCopy()..['companion_name'] = '小夏';
    await controller.save(copy);
    expect(controller.settings['cognition']['custom']['value'], 17);
  });
}
