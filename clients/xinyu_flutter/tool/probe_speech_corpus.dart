// Offline benchmark of the app's actual native worker, with a frozen manifest.
// References are scored separately; only PCM is ever passed to the recognizer.
import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';
import 'package:xinyu_flutter/data/local_asr_worker.dart';

import 'probe_local_asr.dart' show pcmWave;

Future<void> main(List<String> args) async {
  if (args.length != 5) {
    throw ArgumentError('MODEL_DIR MANIFEST OUTPUT_JSON fresh|reuse PACING_MS');
  }
  final manifest = await File(args[1]).readAsBytes();
  final cases = jsonDecode(utf8.decode(manifest)) as List;
  if (cases.isEmpty || cases.length > 80) throw StateError('bounded_cases');
  final fresh = args[3] == 'fresh';
  final pacing = int.parse(args[4]);
  final rows = <Map<String, Object?>>[];
  LocalAsrWorker create() =>
      LocalAsrWorker(libraryPath: Platform.environment['XINYU_ASR_NATIVE_DIR']);
  final shared = fresh ? null : create();
  final protocol = {
    'manifest_sha256': sha256.convert(manifest).toString(),
    'mode': args[3],
    'pacing_ms': pacing,
    'cases': cases.length,
    'max_seconds_per_case': 45,
    'remote_asr_calls': 0,
    'platform':
        '${Platform.operatingSystem} ${Platform.operatingSystemVersion}',
  };
  await File('${args[2]}.protocol.json').writeAsString(jsonEncode(protocol));
  try {
    for (final item in cases) {
      final sample = item as Map<String, dynamic>;
      final worker = shared ?? create();
      final done = Completer<String>();
      final finished = done.future.timeout(const Duration(seconds: 45));
      unawaited(finished.catchError((Object _) => ''));
      final clock = Stopwatch()..start();
      var feedAt = 0, stopAt = 0, partials = 0;
      int? firstText;
      final row = <String, Object?>{
        'id': sample['id'],
        'group': sample['group'],
        'seconds': sample['seconds'],
        'pacing_ms': pacing,
      };
      try {
        final bytes = await File(sample['path'] as String).readAsBytes();
        if (sha256.convert(bytes).toString() != sample['sha256']) {
          throw StateError('audio_checksum');
        }
        final pcm = pcmWave(bytes);
        if (pcm.length > 640000) throw StateError('maximum_audio_20_seconds');
        final loadAt = clock.elapsedMicroseconds;
        await worker.start(
          args[0],
          (text, finalResult) {
            if (text.isNotEmpty) {
              firstText ??= clock.elapsedMicroseconds - feedAt;
            }
            if (!finalResult) partials++;
            if (finalResult && !done.isCompleted) done.complete(text);
          },
          (code) {
            if (!done.isCompleted) done.completeError(StateError(code));
          },
        );
        row['model_and_stream_start_ms'] =
            (clock.elapsedMicroseconds - loadAt) / 1000;
        feedAt = clock.elapsedMicroseconds;
        for (var offset = 0; offset < pcm.length; offset += 6400) {
          worker.add(
            Uint8List.sublistView(
              pcm,
              offset,
              (offset + 6400).clamp(0, pcm.length),
            ),
          );
          if (pacing > 0) {
            await Future<void>.delayed(Duration(milliseconds: pacing));
          }
        }
        stopAt = clock.elapsedMicroseconds;
        worker.finish();
        row['text'] = await finished;
        row['final_ms_after_stop'] =
            (clock.elapsedMicroseconds - stopAt) / 1000;
        row['first_text_ms_after_pcm'] = firstText == null
            ? null
            : firstText! / 1000;
        row['partial_updates'] = partials;
        row['peak_process_rss_mib'] = ProcessInfo.maxRss / 1048576;
        row['status'] = 'decoded';
      } catch (error) {
        row['status'] = 'failed';
        row['error'] = error.toString();
      } finally {
        if (fresh) await worker.dispose();
      }
      rows.add(row);
      await File(args[2])
          .writeAsString(const JsonEncoder.withIndent('  ').convert(rows));
      stdout.writeln(jsonEncode(row));
    }
  } finally {
    await shared?.dispose();
  }
  if (rows.any((row) => row['status'] == 'failed')) exitCode = 1;
}
