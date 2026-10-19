// Runs the same worker used by the app against public PCM WAV recordings.
// No microphone, network, chat model, APK or daily-use database is involved.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import 'package:xinyu_flutter/data/local_asr_worker.dart';

Uint8List pcmWave(Uint8List file) {
  final data = ByteData.sublistView(file);
  if (ascii.decode(file.sublist(0, 4)) != 'RIFF' ||
      ascii.decode(file.sublist(8, 12)) != 'WAVE') {
    throw const FormatException('PCM WAV required');
  }
  var mono16k = false;
  for (var offset = 12; offset + 8 <= file.length;) {
    final name = ascii.decode(file.sublist(offset, offset + 4));
    final size = data.getUint32(offset + 4, Endian.little);
    final start = offset + 8;
    if (start + size > file.length) {
      throw const FormatException('Truncated WAV');
    }
    if (name == 'fmt ') {
      mono16k =
          data.getUint16(start, Endian.little) == 1 &&
          data.getUint16(start + 2, Endian.little) == 1 &&
          data.getUint32(start + 4, Endian.little) == 16000 &&
          data.getUint16(start + 14, Endian.little) == 16;
    }
    if (name == 'data') {
      if (!mono16k) throw const FormatException('16 kHz mono PCM16 required');
      return Uint8List.sublistView(file, start, start + size);
    }
    offset = start + size + size % 2;
  }
  throw const FormatException('Missing PCM data');
}

Future<void> main(List<String> args) async {
  if (args.length != 2) {
    throw ArgumentError(
      'Usage: probe_local_asr.dart MODEL_DIRECTORY EVIDENCE_DIRECTORY',
    );
  }
  final output = Directory(args[1]);
  final protocol = <String, Object>{
    'model': 'zipformer-zh-en-2023-02-20-int8',
    'sherpa_onnx': '1.12.14',
    'provider': 'cpu',
    'threads': 2,
    'max_active_paths': 4,
    'samples': ['0.wav', '1.wav', '2.wav', '3.wav', 'silence'],
    'maximum_sessions': 5,
    'maximum_seconds_per_session': 45,
    'remote_calls': 0,
    'pacing_ms': 200,
    'source': 'https://huggingface.co/csukuangfj/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/tree/98590b7ed6443e77b714204da2757d75e1a642f4/test_wavs',
    'platform':
        '${Platform.operatingSystem} ${Platform.operatingSystemVersion}',
  };
  await File('${output.path}/asr-protocol.json')
      .writeAsString(const JsonEncoder.withIndent('  ').convert(protocol));
  final rows = <Map<String, Object?>>[];
  for (final name in protocol['samples'] as List<String>) {
    final worker = LocalAsrWorker(
      libraryPath: Platform.environment['XINYU_ASR_NATIVE_DIR'],
    );
    final timer = Stopwatch()..start();
    final finalText = Completer<String>();
    final result = finalText.future.timeout(const Duration(seconds: 45));
    unawaited(result.catchError((Object _) => ''));
    var partials = 0;
    int? firstMs;
    var feedStart = 0, finishAt = 0;
    final row = <String, Object?>{'sample': name};
    try {
      final file = name == 'silence'
          ? null
          : await File('${output.path}/$name').readAsBytes();
      final audio = file == null ? Uint8List(64000) : pcmWave(file);
      row['sha256'] = sha256.convert(file ?? audio).toString();
      row['audio_seconds'] = audio.length / 32000;
      final readiness = timer.elapsedMilliseconds;
      await worker.start(
        args[0],
        (text, done) {
          if (text.isNotEmpty) {
            firstMs ??= timer.elapsedMilliseconds - feedStart;
          }
          if (!done) partials++;
          if (done && !finalText.isCompleted) finalText.complete(text);
        },
        (code) {
          if (!finalText.isCompleted) finalText.completeError(StateError(code));
        },
      );
      row['load_ms'] = timer.elapsedMilliseconds - readiness;
      feedStart = timer.elapsedMilliseconds;
      for (var offset = 0; offset < audio.length; offset += 6400) {
        worker.add(
          Uint8List.sublistView(
            audio,
            offset,
            (offset + 6400).clamp(0, audio.length),
          ),
        );
        await Future<void>.delayed(const Duration(milliseconds: 200));
      }
      finishAt = timer.elapsedMilliseconds;
      worker.finish();
      row['text'] = await result;
      row['final_ms_after_stop'] = timer.elapsedMilliseconds - finishAt;
      row['first_text_ms'] = firstMs;
      row['partial_updates'] = partials;
      row['peak_process_rss_mib'] = ProcessInfo.maxRss / 1048576;
      row['status'] = 'passed';
      if (name == 'silence' && (row['text'] as String).isNotEmpty) {
        row['status'] = 'failed_silence_hallucination';
      }
    } catch (error) {
      row['status'] = 'failed';
      row['error'] = error.toString();
    } finally {
      await worker.dispose();
      timer.stop();
    }
    rows.add(row);
    stdout.writeln(jsonEncode(row));
    await File('${output.path}/asr-results.json')
        .writeAsString(const JsonEncoder.withIndent('  ').convert(rows));
  }
  if (rows.any((row) => row['status'] != 'passed')) exitCode = 1;
}
