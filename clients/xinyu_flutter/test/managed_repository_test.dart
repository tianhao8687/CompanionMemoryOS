import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/managed_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/data/native_runtime.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

class TestRuntime extends NativeRuntime {
  TestRuntime(this.endpoint);
  final String endpoint;
  int starts = 0, stops = 0;
  bool running = false, fail = false;
  String get token => 'test-epoch-$starts';
  @override
  Future<Map<String, dynamic>> start() async {
    if (fail) throw const CompanionException('测试引擎启动失败');
    if (!running) {
      starts++;
      running = true;
    }
    return {'protocol': 1, 'endpoint': endpoint, 'token': token};
  }

  @override
  Future<void> stop() async {
    if (running) stops++;
    running = false;
  }
}

void main() {
  test(
    'Managed restart renews credentials and preserves binary backup transport',
    () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final runtime = TestRuntime('http://127.0.0.1:${server.port}');
      final repository = ManagedRepository(runtime: runtime);
      addTearDown(() async {
        repository.close();
        await server.close(force: true);
      });
      final backup = Uint8List.fromList([0, 1, 128, 255]);
      final requests = <String>[];
      Map<String, dynamic>? saved;
      server.listen((request) async {
        requests.add(request.uri.path);
        expect(request.headers.value('x-xinyu-token'), runtime.token);
        switch (request.uri.path) {
          case '/':
            request.response.cookies.add(
              Cookie(
                'companion_romance_session_${server.port}',
                'session-${runtime.starts}',
              ),
            );
            request.response.write('synthetic index');
          case '/api/bootstrap':
            expect(request.cookies.single.value, 'session-${runtime.starts}');
            request.response.write(
              jsonEncode({
                'settings': {'companion_name': '小禾'},
                'conversations': [],
                'key_configured': true,
                'credential_persistence_supported': true,
              }),
            );
          case '/api/settings':
            saved = jsonDecode(
              await utf8.decoder.bind(request).join(),
            ) as Map<String, dynamic>;
            request.response.write(
              jsonEncode({'settings': saved!['settings']}),
            );
          case '/api/local/backup':
            request.response.add(backup);
          case '/api/local/restore':
            expect(
              request.headers.contentType?.mimeType,
              'application/octet-stream',
            );
            final bytes = await request.fold<List<int>>(
              [],
              (previous, chunk) => previous..addAll(chunk),
            );
            expect(bytes, backup);
            request.response.write('{"restart_required":true}');
          default:
            request.response.statusCode = 404;
        }
        await request.response.close();
      });
      final snapshot = await repository.bootstrap();
      expect(snapshot.capabilities['key_configured'], true);
      await repository.bootstrap();
      expect(runtime.starts, 1);
      await repository.saveSettings(
        {'style': 'custom', 'custom_style': '坦诚直接'},
        apiKey: 'synthetic-key',
        rememberKey: true,
      );
      expect(saved!['remember_api_key'], true);
      expect(saved!['clear_api_key'], false);
      expect(saved!['api_key'], 'synthetic-key');
      expect(await repository.connection.backup(), backup);
      await repository.connection.restore(backup);
      await repository.restart();
      expect(runtime.stops, 1);
      expect(() => repository.connection, throwsA(isA<CompanionException>()));
      await repository.bootstrap();
      expect(runtime.starts, 2);
      expect(requests.where((p) => p == '/api/local/restore'), hasLength(1));
      repository.close();
      expect(repository.bootstrap(), throwsA(isA<CompanionException>()));
      expect(runtime.starts, 2);
    },
  );

  test(
    'Startup failure stays visible and never changes to demo replies',
    () async {
      final runtime = TestRuntime('http://127.0.0.1:1')..fail = true;
      final controller = CompanionController(
        repository: ManagedRepository(runtime: runtime),
      );
      addTearDown(controller.dispose);
      await expectLater(
        controller.initialize(),
        throwsA(isA<CompanionException>()),
      );
      expect(controller.isDemo, false);
      expect(controller.connected, false);
      expect(controller.ready, false);
      expect(controller.error, '测试引擎启动失败');
      expect(controller.messages, isEmpty);
    },
  );
}
