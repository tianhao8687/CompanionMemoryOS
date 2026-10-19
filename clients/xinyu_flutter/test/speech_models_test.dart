import 'dart:async';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/speech_models.dart';

void main() {
  late Directory root;
  late HttpServer server;
  late SpeechModels models;
  var calls = 0;
  final bytes = List<int>.generate(10000, (i) => i % 255);
  final specs = [
    SpeechModelFile(
      'test.onnx',
      bytes.length,
      sha256.convert(bytes).toString(),
    ),
  ];
  setUp(() async {
    root = await Directory.systemTemp.createTemp('xinyu-voice-test-');
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    calls = 0;
    models = SpeechModels(
      directory: () async => root,
      files: specs,
      source: (name) => Uri.parse('http://127.0.0.1:${server.port}/$name'),
    );
  });
  tearDown(() async {
    models.dispose();
    await server.close(force: true);
    await root.delete(recursive: true);
  });

  test(
    'inspection stays offline; download verifies, reuses, detects corruption',
    () async {
      server.listen((request) async {
        calls++;
        expect(request.headers.value('range'), 'bytes=0-9999');
        request.response.statusCode = 206;
        request.response.headers.set('content-range', 'bytes 0-9999/10000');
        request.response.add(bytes);
        await request.response.close();
      });
      await models.inspect();
      expect(models.phase, SpeechModelPhase.missing);
      expect(calls, 0);
      await models.download();
      expect(models.ready, isTrue);
      expect(calls, 1);
      expect(await File('${root.path}/test.onnx.part').exists(), isFalse);
      await models.download();
      expect(calls, 1);
      final reopened = SpeechModels(
        directory: () async => root,
        files: specs,
        source: (_) => throw StateError('inspection must stay offline'),
      );
      await reopened.inspect();
      expect(reopened.ready, isTrue);
      expect(reopened.verificationPasses, 0);
      await File('${root.path}/test.onnx')
          .writeAsBytes(List.filled(bytes.length, 0));
      await reopened.inspect();
      expect(reopened.ready, isFalse);
      expect(reopened.verificationPasses, 1);
      reopened.dispose();
      await models.inspect();
      expect(models.ready, isFalse);
      expect(calls, 1);
    },
  );

  test('wrong checksum never becomes an available model', () async {
    server.listen((request) async {
      request.response.add(List.filled(bytes.length, 0));
      await request.response.close();
    });
    await models.download();
    expect(models.phase, SpeechModelPhase.error);
    expect(models.message, contains('校验失败'));
    expect(await File('${root.path}/test.onnx').exists(), isFalse);
    expect(await File('${root.path}/test.onnx.part').exists(), isFalse);
  });

  test(
    'a broken verification receipt triggers hashing rather than trusting it',
    () async {
      await File('${root.path}/test.onnx').writeAsBytes(bytes);
      await File('${root.path}/.verified.json').writeAsString('{broken');
      await models.inspect();
      expect(models.ready, isTrue);
      expect(models.verificationPasses, 1);
      await File('${root.path}/.verified.json')
          .writeAsString('{"version":999}');
      final reopened = SpeechModels(directory: () async => root, files: specs);
      await reopened.inspect();
      expect(reopened.ready, isTrue);
      expect(reopened.verificationPasses, 1);
      reopened.dispose();
    },
  );

  test(
    'partial or mismatched range cannot silently create a truncated model',
    () async {
      server.listen((request) async {
        request.response.statusCode = 206;
        request.response.headers.set('content-range', 'bytes 100-9999/10000');
        request.response.add(bytes.sublist(100));
        await request.response.close();
      });
      await models.download();
      expect(models.ready, isFalse);
      expect(models.phase, SpeechModelPhase.error);
      expect(await File('${root.path}/test.onnx.part').exists(), isFalse);
    },
  );

  test(
    'cancel closes a pending transfer and a later explicit retry works',
    () async {
      final receiving = Completer<void>();
      final release = Completer<void>();
      server.listen((request) async {
        calls++;
        if (calls == 1) {
          request.response.contentLength = bytes.length;
          request.response.add(bytes.sublist(0, 10));
          await request.response.flush();
          receiving.complete();
          await release.future;
          try {
            await request.response.close();
          } catch (_) {}
        } else {
          request.response.add(bytes);
          await request.response.close();
        }
      });
      final downloading = models.download();
      await receiving.future;
      await models.cancelDownload();
      release.complete();
      await downloading;
      expect(models.ready, isFalse);
      expect(await File('${root.path}/test.onnx.part').exists(), isFalse);
      await models.download();
      expect(models.ready, isTrue);
      expect(calls, 2);
    },
  );
}
