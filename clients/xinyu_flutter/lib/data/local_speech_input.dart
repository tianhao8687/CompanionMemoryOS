import 'dart:async';
import 'dart:typed_data';

import 'package:record/record.dart';

import 'local_asr_worker.dart';
import 'speech_input.dart';
import 'speech_models.dart';

/// PCM stays in memory and goes directly to the local worker. No repository,
/// socket, system recognizer, API key or cloud fallback exists on this path.
class LocalSpeechInput implements SpeechInput {
  LocalSpeechInput({
    SpeechModels? models,
    AudioRecorder Function()? recorder,
    SpeechDecoder Function()? decoder,
  }) : models = models ?? SpeechModels(),
       _createRecorder = recorder ?? AudioRecorder.new,
       _createDecoder = decoder ?? LocalAsrWorker.new;

  final SpeechModels models;
  final AudioRecorder Function() _createRecorder;
  final SpeechDecoder Function() _createDecoder;
  AudioRecorder? _recorder;
  SpeechDecoder? _decoder;
  StreamSubscription<Uint8List>? _audio;
  StreamSubscription<RecordState>? _states;
  Completer<void>? _audioDone;
  void Function(String)? _status, _error;
  int _generation = 0, _total = 0;
  bool _stopping = false;
  Future<void> _opening = Future.value();
  Future<void>? _cancelling;
  Future<void>? _preparing, _decodingReady;
  bool _disposed = false;

  /// Prepare without microphone permission, recording, or network access.
  Future<void> prepare() =>
      _preparing ??= _prepare().whenComplete(() => _preparing = null);

  Future<void> _prepare() async {
    final generation = _generation;
    await models.inspect();
    if (_disposed || generation != _generation || !models.ready) return;
    final directory = await models.directory;
    if (_disposed || generation != _generation) return;
    final decoder = _decoder ??= _createDecoder();
    try {
      await decoder.prepare(directory.path);
    } catch (_) {
      if (identical(_decoder, decoder)) _decoder = null;
      await decoder.dispose();
      // A later explicit start can try again and report the error in the UI.
    }
  }

  Future<void> releaseModel() async {
    await cancel();
    final decoder = _decoder;
    _decoder = null;
    await decoder?.dispose();
  }

  Future<void> dispose() async {
    _disposed = true;
    await releaseModel();
  }

  void _discardDecoder(SpeechDecoder decoder) {
    if (identical(_decoder, decoder)) _decoder = null;
    unawaited(decoder.dispose().catchError((Object _) {}));
  }

  @override
  Future<bool> initialize({
    required void Function(String) onStatus,
    required void Function(String) onError,
  }) async {
    final generation = ++_generation;
    _status = onStatus;
    _error = onError;
    // Unchanged app-private files reuse the persisted verification receipt.
    await models.inspect();
    if (generation != _generation) return false;
    if (!models.ready) {
      onError('voice_model_missing');
      return false;
    }
    final recorder = _recorder = _createRecorder();
    final allowed = await recorder.hasPermission();
    if (generation != _generation) return false;
    if (!allowed) onError('error_permission');
    return allowed;
  }

  @override
  Future<List<({String id, String name})>> languages() async => [];

  @override
  Future<void> listen({
    required String? locale,
    required SpeechResult onResult,
  }) => _opening = _listen(onResult);

  Future<void> _listen(SpeechResult onResult) async {
    final generation = _generation;
    bool current() => generation == _generation;
    _stopping = false;
    _total = 0;
    try {
      final directory = await models.directory;
      if (!current()) return;
      final decoder = _decoder ??= _createDecoder();
      var ready = false, queued = 0;
      final pending = <Uint8List>[];
      final decoding = _decodingReady = decoder
          .start(
            directory.path,
            (text, finalResult) {
              if (current()) onResult(text, finalResult);
            },
            (code) {
              _discardDecoder(decoder);
              if (current()) _error?.call(code);
            },
          )
          .then((_) {
            if (!current()) return;
            ready = true;
            for (final bytes in pending) {
              if (!current()) break;
              decoder.add(bytes);
            }
            pending.clear();
            if (current() && !_stopping) _status?.call('decoderReady');
          })
          .catchError((Object _) {
            if (current()) _discardDecoder(decoder);
            if (current()) _error?.call('voice_model_load');
          });
      unawaited(decoding);
      if (!current()) return;
      final recorder = _recorder!;
      await recorder.setOnConfigChanged((config) {
        if (current() &&
            (config.sampleRate != 16000 ||
                config.numChannels != 1 ||
                config.encoder != AudioEncoder.pcm16bits)) {
          _error?.call('voice_audio_format');
        }
      });
      if (!current()) return;
      _states = recorder.onStateChanged().listen(
        (state) {
          if (current() && !_stopping && state == RecordState.pause) {
            _error?.call('voice_interrupted');
          }
        },
        onError: (Object _) {
          if (current()) _error?.call('error_audio');
        },
      );
      final stream = await recorder.startStream(
        const RecordConfig(
          encoder: AudioEncoder.pcm16bits,
          sampleRate: 16000,
          numChannels: 1,
          streamBufferSize: 6400,
          audioInterruption: AudioInterruptionMode.pause,
        ),
      );
      if (!current()) return;
      final audioDone = _audioDone = Completer<void>();
      _audio = stream.listen(
        (bytes) {
          if (!current()) return;
          final remaining = 60 * 16000 * 2 - _total;
          if (remaining <= 0) {
            unawaited(stop());
            return;
          }
          final audio = bytes.length <= remaining
              ? bytes
              : Uint8List.sublistView(bytes, 0, remaining);
          _total += audio.length;
          if (ready) {
            decoder.add(audio);
          } else {
            queued += audio.length;
            if (queued > 640000) {
              _error?.call('voice_too_slow');
              return;
            }
            pending.add(Uint8List.fromList(audio));
          }
          if (_total >= 60 * 16000 * 2) unawaited(stop());
        },
        onError: (Object _) {
          if (current()) _error?.call('error_audio');
        },
        onDone: () {
          if (!audioDone.isCompleted) audioDone.complete();
          if (current() && !_stopping) _error?.call('voice_interrupted');
        },
      );
      _status?.call(ready ? 'listening' : 'buffering');
    } catch (_) {
      if (current()) _error?.call('voice_local_unavailable');
    }
  }

  @override
  Future<void> stop() async {
    if (_stopping || _decoder == null) return;
    _stopping = true;
    final generation = _generation;
    _status?.call('done');
    try {
      await _recorder?.stop();
      await _audioDone?.future.timeout(const Duration(seconds: 2));
      await _decodingReady;
      if (generation == _generation) _decoder?.finish();
    } catch (_) {
      if (generation == _generation) _error?.call('voice_interrupted');
    }
  }

  @override
  Future<void> cancel() =>
      _cancelling ??= _cancel().whenComplete(() => _cancelling = null);
  Future<void> _cancel() async {
    ++_generation;
    _stopping = true;
    // A delayed native start must finish before disposal, otherwise it can reopen
    // the microphone after the sheet has closed.
    await _opening;
    await _audio?.cancel();
    await _states?.cancel();
    final recorder = _recorder;
    _recorder = null;
    _audio = null;
    _states = null;
    try {
      await recorder?.cancel();
    } finally {
      try {
        await recorder?.dispose();
      } finally {
        // Stop this utterance, retaining only the model while the sheet is open.
        await _decoder?.cancel();
      }
    }
  }
}
