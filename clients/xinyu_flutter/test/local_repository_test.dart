import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/local_repository.dart';
import 'package:xinyu_flutter/data/models.dart';

void main() {
  test('Only explicitly local endpoints are accepted', () {
    for (final url in [
      'https://example.com',
      'http://192.168.1.1:8765',
      'http://localhost@evil.test',
      'http://localhost/path',
      'http://localhost?x=1',
    ]) {
      expect(
        () => LocalRepository.validateEndpoint(url),
        throwsA(isA<CompanionException>()),
      );
    }
    expect(
      LocalRepository.validateEndpoint('http://127.0.0.1:8766').port,
      8766,
    );
  });

  test('Cookie handshake, request header and split UTF-8 stream match backend', () async {
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    final repository = LocalRepository(
      'http://127.0.0.1:${server.port}',
      clientToken: 'synthetic-launch-token',
    );
    addTearDown(() async {
      repository.close();
      await server.close(force: true);
    });
    final requests = <String>[];
    server.listen((request) async {
      requests.add(request.uri.path);
      expect(request.headers.value('x-xinyu-token'), 'synthetic-launch-token');
      if (request.uri.path == '/') {
        request.response.cookies.add(
          Cookie('companion_romance_session_${server.port}', 'test-session'),
        );
        request.response.write('test index');
      } else {
        expect(request.cookies.single.value, 'test-session');
        expect(request.headers.value('x-companion-client'), 'local-web');
        if (request.uri.path == '/api/bootstrap') {
          request.response.write(
            jsonEncode({
              'settings': {'companion_name': '小禾'},
              'conversations': [],
            }),
          );
        } else if (request.uri.path == '/api/chat/stream') {
          final body =
              jsonDecode(await utf8.decoder.bind(request).join()) as Map;
          expect(body['request_id'], 'stable-id');
          expect(body['image_ids'], ['synthetic-local-image']);
          final data = utf8.encode(
            '${jsonEncode({'type': 'delta', 'text': '你好'})}\n${jsonEncode({'type': 'result', 'result': {}})}\n',
          );
          for (var i = 0; i < data.length; i += 2) {
            request.response.add(
              data.sublist(i, (i + 2).clamp(0, data.length)),
            );
            await request.response.flush();
          }
        }
      }
      await request.response.close();
    });
    final snapshot = await repository.bootstrap();
    expect(snapshot.settings['companion_name'], '小禾');
    final events = await repository
        .send('chat', 'stable-id', '你好', imageIds: ['synthetic-local-image'])
        .toList();
    expect(events.first['text'], '你好');
    expect(events.last['type'], 'result');
    expect(requests, ['/', '/api/bootstrap', '/api/chat/stream']);
  });
}
