import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:xinyu_flutter/data/local_asr_worker.dart';
import 'package:xinyu_flutter/data/local_speech_input.dart';
import 'package:xinyu_flutter/data/speech_input.dart';
import 'package:xinyu_flutter/data/speech_models.dart';
import 'package:xinyu_flutter/state/voice_input.dart';

class TestModels extends SpeechModels {
  TestModels({this.available = true});
  bool available;
  @override
  Future<void> inspect() async {
    phase = available ? SpeechModelPhase.ready : SpeechModelPhase.missing;
  }

  @override
  Future<Directory> get directory async => Directory.systemTemp;
}

class TestDecoder implements SpeechDecoder {
  final packets = <Uint8List>[];
  SpeechResult? result;
  int starts = 0, finishes = 0, disposals = 0, loads = 0, cancels = 0;
  Completer<void>? loadGate;
  Future<void>? _preparing;
  @override
  Future<void> prepare(String directory) => _preparing ??= () async {
    loads++;
    await loadGate?.future;
  }();
  @override
  Future<void> start(
    String directory,
    SpeechResult onResult,
    void Function(String) onError,
  ) async {
    starts++;
    await prepare(directory);
    result = onResult;
  }

  @override
  void add(Uint8List bytes) {
    packets.add(bytes);
    result?.call('今天有点累', false);
  }

  @override
  void finish() {
    finishes++;
    result?.call('今天有点累但是很开心', true);
  }

  @override
  Future<void> cancel() async {
    cancels++;
  }

  @override
  Future<void> dispose() async {
    disposals++;
  }
}

void main() {
  final binding = TestWidgetsFlutterBinding.ensureInitialized();
  final messenger = binding.defaultBinaryMessenger;
  const channel = MethodChannel('com.llfbandit.record/messages');
  const codec = StandardMethodCodec();
  final calls = <MethodCall>[];
  final eventChannels = <String>[];
  String? recorderId;
  Completer<void>? startGate;
  Future<void> audio(Uint8List? bytes) async {
    final done = Completer<void>();
    messenger.handlePlatformMessage(
      'com.llfbandit.record/eventsRecord/$recorderId',
      bytes == null ? null : codec.encodeSuccessEnvelope(bytes),
      (_) => done.complete(),
    );
    await done.future;
  }

  setUp(() {
    calls.clear();
    startGate = null;
    messenger.setMockMethodCallHandler(channel, (call) async {
      calls.add(call);
      final arguments = call.arguments as Map;
      if (call.method == 'create') {
        recorderId = arguments['recorderId'] as String;
        for (final name in ['events', 'eventsRecord']) {
          final path = 'com.llfbandit.record/$name/$recorderId';
          eventChannels.add(path);
          messenger.setMockMethodCallHandler(
            MethodChannel(path),
            (_) async => null,
          );
        }
      }
      if (call.method == 'hasPermission') return true;
      if (call.method == 'startStream') await startGate?.future;
      if (call.method == 'stop') {
        await audio(Uint8List(3200));
        await audio(null);
      }
      return null;
    });
  });
  tearDown(() {
    messenger.setMockMethodCallHandler(channel, null);
    for (final path in eventChannels) {
      messenger.setMockMethodCallHandler(MethodChannel(path), null);
    }
    eventChannels.clear();
  });

  test(
    'preparing never opens the microphone and repeated speech reuses its model',
    () async {
      final decoder = TestDecoder();
      final input = LocalSpeechInput(
        models: TestModels(),
        decoder: () => decoder,
      );
      final voice = VoiceInput(input: input);
      await voice.prepare();
      expect(calls, isEmpty);
      expect(decoder.loads, 1);
      await voice.start();
      await audio(Uint8List(6400));
      await voice.stop();
      await input.cancel();
      expect(decoder.disposals, 0);
      await voice.start();
      await audio(Uint8List(6400));
      await voice.stop();
      expect(decoder.loads, 1);
      expect(decoder.starts, 2);
      voice.dispose();
      await input.releaseModel();
      expect(decoder.disposals, 1);
    },
  );

  test(
    'cold start records and keeps the first audio before model is ready',
    () async {
      final decoder = TestDecoder()..loadGate = Completer<void>();
      final input = LocalSpeechInput(
        models: TestModels(),
        decoder: () => decoder,
      );
      final voice = VoiceInput(input: input);
      await voice.start();
      expect(voice.phase, VoicePhase.listening);
      expect(voice.message, contains('开头会保留'));
      await audio(Uint8List.fromList([1, 2, 3, 4]));
      expect(decoder.packets, isEmpty);
      decoder.loadGate!.complete();
      await Future<void>.delayed(Duration.zero);
      expect(decoder.packets.single, [1, 2, 3, 4]);
      expect(voice.text, '今天有点累');
      await voice.stop();
      voice.dispose();
      await input.releaseModel();
    },
  );

  test(
    'closing while loading stops microphone before loading completes',
    () async {
      final decoder = TestDecoder()..loadGate = Completer<void>();
      final input = LocalSpeechInput(
        models: TestModels(),
        decoder: () => decoder,
      );
      final voice = VoiceInput(input: input);
      await voice.start();
      await audio(Uint8List(6400));
      voice.close();
      await input.cancel();
      expect(calls.any((c) => c.method == 'dispose'), isTrue);
      expect(decoder.loadGate!.isCompleted, isFalse);
      decoder.loadGate!.complete();
      await Future<void>.delayed(Duration.zero);
      expect(decoder.packets, isEmpty);
      expect(voice.text, isEmpty);
      voice.dispose();
      await input.releaseModel();
    },
  );

  test(
    'stop during cold loading flushes queued audio and tail exactly once',
    () async {
      final decoder = TestDecoder()..loadGate = Completer<void>();
      final input = LocalSpeechInput(
        models: TestModels(),
        decoder: () => decoder,
      );
      final voice = VoiceInput(input: input);
      await voice.start();
      await audio(Uint8List(6400));
      final stopping = voice.stop();
      await Future<void>.delayed(Duration.zero);
      expect(voice.phase, VoicePhase.finishing);
      expect(decoder.packets, isEmpty);
      decoder.loadGate!.complete();
      await stopping;
      expect(decoder.packets.map((p) => p.length), [6400, 3200]);
      expect(decoder.finishes, 1);
      expect(voice.phase, VoicePhase.review);
      voice.dispose();
      await input.releaseModel();
    },
  );

  test(
    'PCM conversion preserves odd boundaries and signed little-endian samples',
    () {
      final pcm = Pcm16Samples();
      expect(pcm.convert(Uint8List.fromList([0])), isEmpty);
      expect(pcm.convert(Uint8List(0)), isEmpty);
      expect(pcm.convert(Uint8List.fromList([128, 255, 127, 0])), [
        -1,
        32767 / 32768,
      ]);
      expect(pcm.hasPartialSample, isTrue);
      expect(pcm.convert(Uint8List.fromList([0])), [0]);
      expect(pcm.hasPartialSample, isFalse);
    },
  );

  test(
    'recorder PCM including final tail reaches local decoder without files',
    () async {
      final decoder = TestDecoder();
      final input = LocalSpeechInput(
        models: TestModels(),
        decoder: () => decoder,
      );
      final voice = VoiceInput(input: input);
      expect(calls, isEmpty);
      await voice.start();
      expect(voice.phase, VoicePhase.listening);
      final config =
          calls.singleWhere((c) => c.method == 'startStream').arguments as Map;
      expect(config['encoder'], 'pcm16bits');
      expect(config['sampleRate'], 16000);
      expect(config['numChannels'], 1);
      expect(config.containsKey('path'), isFalse);
      await audio(Uint8List(6400));
      await voice.stop();
      expect(decoder.packets.map((v) => v.length), [6400, 3200]);
      expect(decoder.finishes, 1);
      expect(voice.phase, VoicePhase.review);
      expect(voice.text, '今天有点累但是很开心');
      voice.dispose();
      await input.cancel();
      expect(decoder.disposals, 1);
      expect(calls.any((c) => c.method == 'start'), isFalse);
    },
  );

  test(
    'missing model never asks for mic permission or starts any recognizer',
    () async {
      final decoder = TestDecoder();
      final input = LocalSpeechInput(
        models: TestModels(available: false),
        decoder: () => decoder,
      );
      final voice = VoiceInput(input: input);
      await voice.start();
      expect(voice.phase, VoicePhase.error);
      expect(voice.message, contains('免费'));
      expect(calls, isEmpty);
      expect(decoder.starts, 0);
      voice.dispose();
      await input.cancel();
    },
  );

  test(
    'cancel during native start waits then releases recorder and model',
    () async {
      startGate = Completer<void>();
      final decoder = TestDecoder();
      final input = LocalSpeechInput(
        models: TestModels(),
        decoder: () => decoder,
      );
      final voice = VoiceInput(input: input);
      final starting = voice.start();
      while (!calls.any((c) => c.method == 'startStream')) {
        await Future<void>.delayed(const Duration(milliseconds: 1));
      }
      final closing = voice.close();
      startGate!.complete();
      await starting;
      await closing;
      expect(voice.active, isFalse);
      expect(calls.any((c) => c.method == 'dispose'), isTrue);
      expect(decoder.disposals, 1);
      decoder.result?.call('迟到的文字', true);
      expect(voice.text, isEmpty);
      voice.dispose();
    },
  );
}
