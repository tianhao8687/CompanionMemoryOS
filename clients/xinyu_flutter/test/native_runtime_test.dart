import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/managed_repository.dart';
import 'package:xinyu_flutter/data/models.dart';
import 'package:xinyu_flutter/data/native_runtime.dart';
import 'package:xinyu_flutter/state/companion_controller.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('Android startup failure explains the stage without exposing platform details', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    final messenger =
        TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
    final controller = CompanionController(repository: ManagedRepository());
    addTearDown(() async {
      controller.dispose();
      await Future<void>.delayed(Duration.zero);
      messenger.setMockMethodCallHandler(NativeRuntime.channel, null);
      debugDefaultTargetPlatformOverride = null;
    });
    var fail = true;
    messenger.setMockMethodCallHandler(NativeRuntime.channel, (call) async {
      if (call.method == 'stop') return null;
      if (fail) {
        throw PlatformException(
          code: 'engine_start',
          message: 'private-path and synthetic-secret must not appear in UI',
        );
      }
      return {
        'protocol': 1,
        'endpoint': 'http://127.0.0.1:12345',
        'token': 'synthetic-token',
      };
    });
    await expectLater(
      controller.initialize(),
      throwsA(isA<CompanionException>()),
    );
    expect(controller.connected, false);
    expect(controller.isDemo, false);
    expect(controller.error, contains('A03'));
    expect(controller.error, isNot(contains('检查本地服务')));
    expect(controller.error, isNot(contains('synthetic-secret')));
    expect(controller.error, isNot(contains('private-path')));
    fail = false;
    final retry = NativeRuntime();
    expect((await retry.start())['protocol'], 1);
    await retry.stop();
  });
}
