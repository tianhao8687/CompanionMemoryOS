import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:isolate';

import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:path_provider/path_provider.dart';

enum SpeechModelPhase {
  unchecked,
  checking,
  missing,
  downloading,
  ready,
  error,
}

class SpeechModelFile {
  const SpeechModelFile(this.name, this.bytes, this.sha256);
  final String name, sha256;
  final int bytes;
}

/// Apache-2.0 model, pinned by content, not by the download host's mutable branch.
const speechModelId = 'zipformer-zh-en-2023-02-20-int8';
const speechModelFiles = [
  SpeechModelFile(
    'encoder-epoch-99-avg-1.int8.onnx',
    181895032,
    '8fa764187a261844f859d7143ebaa563af5d10adfece4c18a8f414c88cba2a9b',
  ),
  SpeechModelFile(
    'decoder-epoch-99-avg-1.onnx',
    13876452,
    '2e3b5ec371f8899ee6acd829fd753ba45772df57a91bdf37cde3136354e7db7d',
  ),
  SpeechModelFile(
    'joiner-epoch-99-avg-1.int8.onnx',
    3228404,
    '1ed689c5ed19dbaa725d9d191bb4822b5f4855a39e1ffd28cbc1f340d25b2ee0',
  ),
  SpeechModelFile(
    'tokens.txt',
    56317,
    'a8e0e4ec53810e433789b54a5c0134a7eaa2ffca595a6334d54c00da858841d3',
  ),
];

Uri speechModelUrl(String name) => Uri.https(
  'modelscope.cn',
  '/models/pkufool/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/resolve/master/$name',
);

Future<bool> _validModelFile(String path, SpeechModelFile spec) async {
  final file = File(path);
  if (!await file.exists() || await file.length() != spec.bytes) return false;
  return (await sha256.bind(file.openRead()).first).toString() == spec.sha256;
}

Future<List<String>?> _modelStamp(
  String path,
  List<SpeechModelFile> files,
) async {
  final stamp = <String>[];
  for (final spec in files) {
    final stat = await File('$path/${spec.name}').stat();
    if (stat.type != FileSystemEntityType.file || stat.size != spec.bytes) {
      return null;
    }
    stamp.add('${spec.name}:${stat.size}:${stat.modified}:${stat.changed}');
  }
  return stamp;
}

/// Only this class accesses the network. Opening the sheet and recognizing speech
/// never download anything. Each completed file is verified before an atomic rename.
class SpeechModels extends ChangeNotifier {
  SpeechModels({
    Future<Directory> Function()? directory,
    HttpClient Function()? client,
    this.files = speechModelFiles,
    Uri Function(String)? source,
  }) : _directory = directory ?? _defaultDirectory,
       _clientFactory = client ?? HttpClient.new,
       _source = source ?? speechModelUrl;

  final Future<Directory> Function() _directory;
  final HttpClient Function() _clientFactory;
  final Uri Function(String) _source;
  final List<SpeechModelFile> files;
  SpeechModelPhase phase = SpeechModelPhase.unchecked;
  String message = '';
  int received = 0;
  int get total => files.fold(0, (n, f) => n + f.bytes);
  bool get ready => phase == SpeechModelPhase.ready;
  bool get busy =>
      phase == SpeechModelPhase.checking ||
      phase == SpeechModelPhase.downloading;
  Future<Directory>? _resolved;
  Future<void>? _operation;
  HttpClient? _client;
  int _generation = 0;
  bool _disposed = false;
  List<String>? _verifiedStamp;
  int verificationPasses = 0;

  String get _manifest => sha256
      .convert(
        utf8.encode(
          jsonEncode([
            for (final file in files) [file.name, file.bytes, file.sha256],
          ]),
        ),
      )
      .toString();

  Future<List<String>?> _readReceipt(String path) async {
    try {
      final receipt = File('$path/.verified.json');
      if (await receipt.length() > 8192) return null;
      final data = jsonDecode(await receipt.readAsString());
      if (data is! Map ||
          data['version'] != 1 ||
          data['manifest'] != _manifest) {
        return null;
      }
      final stamp = data['stamp'];
      if (stamp is! List ||
          stamp.length != files.length ||
          stamp.any((v) => v is! String)) {
        return null;
      }
      return stamp.cast<String>();
    } catch (_) {
      return null;
    }
  }

  Future<void> _saveReceipt(String path, List<String>? stamp) async {
    if (stamp == null) return;
    // The receipt lives beside the immutable weights in app-private storage.
    // It is valid only for this manifest and the unchanged file metadata. Missing,
    // corrupt or outdated receipts cause a full hash check, never blind loading.
    try {
      final pending = File('$path/.verified.json.part');
      await pending.writeAsString(
        jsonEncode({'version': 1, 'manifest': _manifest, 'stamp': stamp}),
        flush: true,
      );
      await pending.rename('$path/.verified.json');
    } on FileSystemException {
      /* Optional cache: failed writes do not block ASR. */
    }
  }

  static Future<Directory> _defaultDirectory() async {
    final parent = await getApplicationSupportDirectory();
    return Directory('${parent.path}/voice/$speechModelId');
  }

  Future<Directory> get directory => _resolved ??= _directory();
  void _emit() {
    if (!_disposed) notifyListeners();
  }

  bool _current(int generation) => !_disposed && generation == _generation;

  Future<void> inspect() =>
      _operation ??= _inspect().whenComplete(() => _operation = null);
  Future<void> _inspect() async {
    final generation = ++_generation;
    phase = SpeechModelPhase.checking;
    message = '';
    _emit();
    try {
      final path = (await directory).path;
      final specs = files;
      final stamp = await _modelStamp(path, specs);
      _verifiedStamp ??= await _readReceipt(path);
      // Hash after installation/download or a file change. Unchanged app-private
      // weights reuse that verified receipt across recordings and app restarts.
      final cached = stamp != null && listEquals(stamp, _verifiedStamp);
      if (!cached) verificationPasses++;
      final valid =
          cached ||
          await Isolate.run(() async {
            for (final spec in specs) {
              if (!await _validModelFile('$path/${spec.name}', spec)) {
                return false;
              }
            }
            return true;
          });
      if (!_current(generation)) return;
      final after = await _modelStamp(path, specs);
      final unchanged = valid && stamp != null && listEquals(stamp, after);
      _verifiedStamp = unchanged ? after : null;
      if (unchanged && !cached) await _saveReceipt(path, after);
      phase = unchanged ? SpeechModelPhase.ready : SpeechModelPhase.missing;
    } catch (_) {
      if (!_current(generation)) return;
      phase = SpeechModelPhase.error;
      message = '无法读取本地语音资源，请检查设备存储。';
    }
    _emit();
  }

  Future<void> download() =>
      _operation ??= _download().whenComplete(() => _operation = null);
  Future<void> _download() async {
    final generation = ++_generation;
    phase = SpeechModelPhase.downloading;
    _verifiedStamp = null;
    message = '';
    received = 0;
    _emit();
    final client = _client = _clientFactory()
      ..connectionTimeout = const Duration(seconds: 20);
    File? partial;
    try {
      final root = await directory;
      await root.create(recursive: true);
      for (final spec in files) {
        if (!_current(generation)) return;
        final path = '${root.path}/${spec.name}';
        if (await Isolate.run(() => _validModelFile(path, spec))) {
          received += spec.bytes;
          _emit();
          continue;
        }
        partial = File('$path.part');
        final sink = partial.openWrite();
        var offset = 0;
        try {
          // Some model hosts return partial responses even without Range. Fetch
          // bounded ranges explicitly, and reject gaps/duplicates/oversized data.
          while (offset < spec.bytes) {
            if (!_current(generation)) return;
            final end = (offset + 4 * 1024 * 1024 - 1).clamp(0, spec.bytes - 1);
            final request = await client
                .getUrl(_source(spec.name))
                .timeout(const Duration(seconds: 20));
            request.headers.set(HttpHeaders.rangeHeader, 'bytes=$offset-$end');
            final response = await request.close().timeout(
              const Duration(seconds: 30),
            );
            final expected = response.statusCode == 200 && offset == 0
                ? spec.bytes
                : end - offset + 1;
            if (response.statusCode != 200 && response.statusCode != 206 ||
                response.statusCode == 200 && offset != 0 ||
                response.statusCode == 206 &&
                    response.headers.value(HttpHeaders.contentRangeHeader) !=
                        'bytes $offset-$end/${spec.bytes}') {
              throw const FormatException('download_range');
            }
            var count = 0;
            await for (final chunk in response.timeout(
              const Duration(seconds: 30),
            )) {
              if (!_current(generation)) return;
              count += chunk.length;
              if (count > expected) {
                throw const FormatException('download_size');
              }
              sink.add(chunk);
              received += chunk.length;
              _emit();
            }
            if (count != expected) {
              throw const FormatException('download_incomplete');
            }
            offset += count;
            await sink.flush();
          }
        } finally {
          await sink.close();
        }
        final partialPath = partial.path;
        if (!await Isolate.run(() => _validModelFile(partialPath, spec))) {
          throw const FormatException('download_checksum');
        }
        if (!_current(generation)) return;
        final target = File(path);
        if (await target.exists()) await target.delete();
        await partial.rename(path);
        partial = null;
      }
      if (_current(generation)) {
        _verifiedStamp = await _modelStamp(root.path, files);
        await _saveReceipt(root.path, _verifiedStamp);
        phase = SpeechModelPhase.ready;
      }
    } catch (error) {
      if (_current(generation)) {
        phase = SpeechModelPhase.error;
        message = error is FileSystemException
            ? '保存失败，请检查设备剩余空间。已完成的资源会保留。'
            : error is FormatException
            ? '资源不完整或校验失败，请重新下载。已完成的资源会保留。'
            : '下载中断，请检查网络后重试。已完成的资源会保留。';
      }
    } finally {
      client.close(force: true);
      if (identical(_client, client)) _client = null;
      if (partial != null && await partial.exists()) {
        try {
          await partial.delete();
        } on FileSystemException {
          /* Best effort partial cleanup. */
        }
      }
      _emit();
    }
  }

  Future<void> cancelDownload() async {
    if (phase != SpeechModelPhase.downloading) return;
    ++_generation;
    _client?.close(force: true);
    await _operation;
    if (_disposed) return;
    phase = SpeechModelPhase.missing;
    message = '下载已取消，已完成的资源会保留。';
    _emit();
  }

  @override
  void dispose() {
    _disposed = true;
    ++_generation;
    _client?.close(force: true);
    super.dispose();
  }
}
