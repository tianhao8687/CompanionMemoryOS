import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import 'models.dart';

/// Owns only the engine launched by this application. No port scanning or ADB.
class NativeRuntime {
  static const channel = MethodChannel('xinyu/local-runtime');
  Process? _process;
  Map<String, dynamic>? _connection;

  Future<Map<String, dynamic>> start() async {
    if (_connection != null) return _connection!;
    if (defaultTargetPlatform == TargetPlatform.android) {
      try {
        final result = await channel.invokeMapMethod<String, dynamic>('start');
        if (result == null) throw const CompanionException('本机引擎没有返回启动结果。');
        return _connection = result;
      } on PlatformException catch (error) {
        // Platform messages can contain sensitive Python/Java details. Display
        // only our fixed stage descriptions, never the raw exception payload.
        throw CompanionException(switch (error.code) {
          'engine_runtime' => '手机运行组件初始化失败（A01），请完全退出应用后重试。',
          'engine_import' => '手机记忆组件加载失败（A02），请更新安装包。',
          'engine_start' => '手机内置记忆引擎启动失败（A03），请重启应用；仍失败时请反馈此代码。',
          _ => '手机内置记忆引擎未能启动（A00），请重启应用后重试。',
        });
      }
    }
    if (!Platform.isWindows) {
      throw const CompanionException('此版本的本地引擎支持 Windows 和 Android。');
    }
    final executable = File(Platform.resolvedExecutable);
    final engine = File('${executable.parent.path}/engine/xinyu-engine.exe');
    final developmentPython = Platform.environment['XINYU_DEVELOPMENT_PYTHON'];
    if (!await engine.exists() && developmentPython == null) {
      throw const CompanionException('安装包缺少本地引擎，请完整解压心隅文件夹后再启动。');
    }
    final local = Platform.environment['LOCALAPPDATA'];
    if (local == null) throw const CompanionException('无法找到当前用户的数据目录。');
    final directory =
        Platform.environment['XINYU_DATA_DIR'] ?? '$local/XinYu/data';
    final process = await Process.start(developmentPython ?? engine.path, [
      if (developmentPython != null) ...['-m', 'companion_agent.local_runtime'],
      '--data-dir',
      directory,
    ], runInShell: false);
    _process = process;
    // Logs must never contain the launch token or model credentials.
    unawaited(process.stderr.drain<void>());
    final ready = Completer<Map<String, dynamic>>();
    process.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen(
          (line) {
            if (ready.isCompleted) return;
            try {
              final value = jsonDecode(line) as Map<String, dynamic>;
              if (value['protocol'] != 1 ||
                  value['token'] is! String ||
                  value['endpoint'] is! String) {
                ready.completeError(
                  CompanionException(value['error'] as String? ?? '本机引擎启动失败。'),
                );
              } else {
                ready.complete(value);
              }
            } catch (_) {
              ready.completeError(const CompanionException('本机引擎返回了无效的启动结果。'));
            }
          },
          onError: (Object _) {
            if (!ready.isCompleted) {
              ready.completeError(const CompanionException('引擎连接中断。'));
            }
          },
          onDone: () {
            if (!ready.isCompleted) {
              ready.completeError(const CompanionException('本机引擎未能启动。'));
            }
          },
        );
    unawaited(
      process.exitCode.then((_) {
        if (identical(_process, process)) {
          _process = null;
          _connection = null;
        }
      }),
    );
    try {
      return _connection = await ready.future.timeout(
        const Duration(seconds: 60),
      );
    } catch (_) {
      await stop();
      rethrow;
    }
  }

  Future<void> stop() async {
    _connection = null;
    if (defaultTargetPlatform == TargetPlatform.android) {
      await channel.invokeMethod<void>('stop');
      return;
    }
    final process = _process;
    _process = null;
    if (process == null) return;
    // The child may already have exited while the app is shutting down.
    await process.stdin.close().catchError((Object _) {});
    try {
      await process.exitCode.timeout(const Duration(seconds: 12));
    } on TimeoutException {
      process.kill();
    }
  }
}
