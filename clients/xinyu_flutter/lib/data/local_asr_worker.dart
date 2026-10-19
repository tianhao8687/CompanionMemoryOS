import 'dart:async';
import 'dart:isolate';
import 'dart:typed_data';

import 'package:sherpa_onnx/sherpa_onnx.dart' as sherpa;

import 'speech_input.dart';

abstract interface class SpeechDecoder {
  Future<void> prepare(String directory);
  Future<void> start(
    String directory,
    SpeechResult onResult,
    void Function(String) onError,
  );
  void add(Uint8List pcm);
  void finish();
  Future<void> cancel();
  Future<void> dispose();
}

/// The UI isolate never loads or decodes the model. One worker owns all native
/// allocations. Utterances get fresh streams; the loaded model is reusable until
/// the voice sheet closes, goes into the background, or receives memory pressure.
class LocalAsrWorker implements SpeechDecoder {
  LocalAsrWorker({this.libraryPath});
  final String? libraryPath;
  ReceivePort? _events;
  SendPort? _commands;
  Isolate? _isolate;
  final _ready = Completer<void>();
  final _exited = Completer<void>();
  Future<void>? _loading;
  Completer<void>? _started;
  SpeechResult? _result;
  Future<void>? _disposing;
  bool _closed = false, _finished = false;
  int _pendingBytes = 0, _session = 0;
  void Function(String)? _error;

  @override
  Future<void> prepare(String directory) => _loading ??= _load(directory);

  Future<void> _load(String directory) async {
    if (_closed) throw StateError('voice_closed');
    final events = _events = ReceivePort();
    // Attach handlers before the isolate can report a load failure.
    final readiness = _ready.future.timeout(const Duration(seconds: 40));
    unawaited(readiness.catchError((Object _) {}));
    events.listen((dynamic event) {
      if (event == null) {
        if (!_exited.isCompleted) _exited.complete();
        if (!_ready.isCompleted) {
          _ready.completeError(StateError('voice_model_load'));
        }
        if (!_closed && !_finished) _error?.call('voice_decode');
        return;
      }
      if (event is! Map) {
        if (!_ready.isCompleted) {
          _ready.completeError(StateError('voice_model_load'));
        }
        if (!_closed) _error?.call('voice_decode');
        return;
      }
      if (event['port'] case final SendPort port) {
        _commands = port;
        if (_closed) port.send('close');
      } else if (event['ready'] == true) {
        if (!_ready.isCompleted) _ready.complete();
      } else if (event['error'] case final String code) {
        if (!_ready.isCompleted) _ready.completeError(StateError(code));
        if (event['session'] == _session && !_closed) {
          if (_started case final started? when !started.isCompleted) {
            started.completeError(StateError(code));
          }
          _error?.call(code);
        }
      } else if (event['session'] != _session || _closed) {
        return;
      } else if (event['started'] == true) {
        if (_started case final started? when !started.isCompleted) {
          started.complete();
        }
      } else if (event['ack'] case final int bytes) {
        _pendingBytes -= bytes;
      } else if (event['text'] case final String text) {
        _finished = event['final'] == true;
        _result?.call(text, _finished);
      }
    });
    _isolate = await Isolate.spawn(
      _runRecognizer,
      (events.sendPort, directory, libraryPath),
      onError: events.sendPort,
      onExit: events.sendPort,
      errorsAreFatal: true,
    );
    await readiness;
  }

  @override
  Future<void> start(
    String directory,
    SpeechResult onResult,
    void Function(String) onError,
  ) async {
    final session = ++_session;
    _result = onResult;
    _error = onError;
    _finished = false;
    _pendingBytes = 0;
    await prepare(directory);
    if (_closed || session != _session) throw StateError('voice_cancelled');
    final started = _started = Completer<void>();
    final waiting = started.future.timeout(const Duration(seconds: 5));
    unawaited(waiting.catchError((Object _) {}));
    _commands!.send({'session': session, 'command': 'start'});
    await waiting;
  }

  @override
  void add(Uint8List pcm) {
    if (_closed || _finished || _commands == null) return;
    _pendingBytes += pcm.length;
    if (_pendingBytes > 640000) {
      _error?.call('voice_too_slow');
      return;
    }
    _commands!.send({
      'session': _session,
      'audio': TransferableTypedData.fromList([pcm]),
    });
  }

  @override
  void finish() {
    if (!_closed) _commands?.send({'session': _session, 'command': 'finish'});
  }

  @override
  Future<void> cancel() async {
    _commands?.send({'session': _session, 'command': 'cancel'});
    ++_session;
    _finished = true;
    _result = null;
    _error = null;
    _pendingBytes = 0;
    if (_started case final started? when !started.isCompleted) {
      started.completeError(StateError('voice_cancelled'));
    }
    _started = null;
  }

  @override
  Future<void> dispose() => _disposing ??= _dispose();
  Future<void> _dispose() async {
    _closed = true;
    await cancel();
    _commands?.send('close');
    if (_events != null) {
      try {
        // Native initialization cannot be interrupted safely halfway through an
        // allocation. Let it finish and consume 'close' before killing a hang.
        await _exited.future.timeout(const Duration(seconds: 45));
      } on TimeoutException {
        _isolate?.kill(priority: Isolate.immediate);
      }
    }
    _events?.close();
    _events = null;
    _commands = null;
  }
}

/// Handles arbitrary byte boundaries from PCM plugins, including odd chunks.
class Pcm16Samples {
  int? _low;
  bool get hasPartialSample => _low != null;
  Float32List convert(Uint8List bytes) {
    final samples = Float32List((bytes.length + (_low == null ? 0 : 1)) ~/ 2);
    var source = 0, target = 0;
    int signed(int value) => value >= 32768 ? value - 65536 : value;
    if (_low != null && bytes.isNotEmpty) {
      samples[target++] = signed(_low! | (bytes[source++] << 8)) / 32768;
      _low = null;
    }
    while (source + 1 < bytes.length) {
      samples[target++] =
          signed(bytes[source] | (bytes[source + 1] << 8)) / 32768;
      source += 2;
    }
    if (source < bytes.length) _low = bytes[source];
    return samples;
  }
}

Future<void> _runRecognizer((SendPort, String, String?) args) async {
  final (events, directory, libraryPath) = args;
  final commands = ReceivePort();
  events.send({'port': commands.sendPort});
  sherpa.OnlineRecognizer? recognizer;
  sherpa.OnlineStream? stream;
  var loaded = false;
  try {
    sherpa.initBindings(libraryPath);
    recognizer = sherpa.OnlineRecognizer(
      sherpa.OnlineRecognizerConfig(
        model: sherpa.OnlineModelConfig(
          transducer: sherpa.OnlineTransducerModelConfig(
            encoder: '$directory/encoder-epoch-99-avg-1.int8.onnx',
            decoder: '$directory/decoder-epoch-99-avg-1.onnx',
            joiner: '$directory/joiner-epoch-99-avg-1.int8.onnx',
          ),
          tokens: '$directory/tokens.txt',
          modelType: 'zipformer',
          provider: 'cpu',
          numThreads: 2,
          debug: false,
        ),
        decodingMethod: 'modified_beam_search',
        maxActivePaths: 4,
        enableEndpoint: true,
        rule1MinTrailingSilence: 2.4,
        rule2MinTrailingSilence: 0.8,
        rule3MinUtteranceLength: 20,
      ),
    );
    loaded = true;
    events.send({'ready': true});
    var pcm = Pcm16Samples();
    final segments = <String>[];
    var previous = '';
    var session = 0;
    await for (final dynamic command in commands) {
      if (command == 'close') break;
      if (command is! Map) continue;
      final id = command['session'];
      if (command['command'] == 'start') {
        stream?.free();
        stream = recognizer.createStream();
        session = id as int;
        pcm = Pcm16Samples();
        segments.clear();
        previous = '';
        events.send({'session': session, 'started': true});
        continue;
      }
      if (id != session || stream == null) continue;
      if (command['command'] == 'cancel') {
        stream.free();
        stream = null;
        segments.clear();
        previous = '';
        pcm = Pcm16Samples();
        continue;
      }
      final finalResult = command['command'] == 'finish';
      if (command['audio'] case final TransferableTypedData audio) {
        final bytes = audio.materialize().asUint8List();
        final samples = pcm.convert(bytes);
        if (samples.isNotEmpty) {
          stream.acceptWaveform(samples: samples, sampleRate: 16000);
        }
        while (recognizer.isReady(stream)) {
          recognizer.decode(stream);
        }
        events.send({'session': session, 'ack': bytes.length});
      } else if (finalResult) {
        if (pcm.hasPartialSample) throw const FormatException('pcm_tail');
        // Flush the encoder's right context before marking input finished.
        stream.acceptWaveform(samples: Float32List(12800), sampleRate: 16000);
        stream.inputFinished();
        while (recognizer.isReady(stream)) {
          recognizer.decode(stream);
        }
      } else {
        throw const FormatException('worker_command');
      }
      final current = recognizer.getResult(stream).text.trim();
      final text = [...segments, if (current.isNotEmpty) current].join('\n');
      if (text.length > 6000) throw const FormatException('transcript_limit');
      if (text != previous || finalResult) {
        events.send({'session': session, 'text': text, 'final': finalResult});
        previous = text;
      }
      if (finalResult) {
        stream.free();
        stream = null;
        segments.clear();
        previous = '';
        pcm = Pcm16Samples();
        continue;
      }
      if (recognizer.isEndpoint(stream)) {
        if (current.isNotEmpty) segments.add(current);
        recognizer.reset(stream);
      }
    }
  } catch (_) {
    events.send({'error': loaded ? 'voice_decode' : 'voice_model_load'});
  } finally {
    stream?.free();
    recognizer?.free();
    commands.close();
  }
}
