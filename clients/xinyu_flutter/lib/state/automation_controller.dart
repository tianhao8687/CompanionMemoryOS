import 'dart:async';

import 'package:flutter/foundation.dart';

import '../data/automation.dart';
import '../data/local_repository.dart';
import '../data/models.dart';
import '../data/user_problem.dart';

/// A projection of the existing engine's configuration and approval queue.
class AutomationController extends ChangeNotifier {
  AutomationController(this.connection, {required this.onActionComplete});
  final LocalRepository? Function() connection;
  final Future<void> Function() onActionComplete;
  AutomationState? state;
  String? error, notice;
  bool loading = false, busy = false;
  bool _disposed = false;
  int _generation = 0;

  LocalRepository? _connection() {
    try {
      return connection();
    } on CompanionException {
      // An optional app connection must not fail chat startup while the native
      // repository is unavailable or restarting.
      return null;
    }
  }

  void _emit() {
    if (!_disposed) notifyListeners();
  }

  void reset() {
    _generation++;
    state = null;
    error = null;
    notice = null;
    loading = busy = false;
    _emit();
    if (_connection() != null) unawaited(refresh(silent: true));
  }

  bool _current(int generation, LocalRepository repository) =>
      !_disposed && generation == _generation && _connection() == repository;

  Future<void> refresh({bool silent = false}) async {
    final repository = _connection();
    if (_disposed || repository == null || loading || busy) return;
    final generation = _generation;
    loading = true;
    if (!silent) error = null;
    _emit();
    try {
      final value = await repository.automation();
      if (_current(generation, repository)) state = AutomationState(value);
    } catch (e) {
      if (_current(generation, repository) && !silent) {
        error = userProblemMessage(e, fallback: '暂时无法读取连接的应用，请重试。');
      }
    } finally {
      if (_current(generation, repository)) {
        loading = false;
        _emit();
      }
    }
  }

  Future<void> _mutate(
    Future<void> Function(LocalRepository repository) action,
  ) async {
    final repository = _connection();
    if (busy || loading || repository == null || _disposed) return;
    final generation = _generation;
    busy = true;
    error = notice = null;
    _emit();
    try {
      await action(repository);
    } catch (e) {
      if (_current(generation, repository)) {
        error = userProblemMessage(e, fallback: '应用操作未完成，请刷新后重试。');
      }
    } finally {
      // Even a failed/timeout request can have changed the server. Read the
      // authoritative queue instead of assuming an operation is safe to retry.
      if (_current(generation, repository)) {
        try {
          final value = await repository.automation();
          if (_current(generation, repository)) state = AutomationState(value);
        } catch (e) {
          if (_current(generation, repository)) {
            error ??= userProblemMessage(e, fallback: '请刷新以核对操作结果。');
          }
        }
        if (_current(generation, repository)) {
          busy = false;
          _emit();
        }
      }
    }
  }

  Future<AutomationState> _fresh(LocalRepository repository) async =>
      AutomationState(await repository.automation());

  Future<void> connectNetease() => _mutate((repository) async {
    final latest = await _fresh(repository);
    if (!latest.supportsNetease) {
      throw const CompanionException(
        '当前运行环境暂不支持网易云音乐连接，请使用心隅 Windows 或 Android 客户端。',
      );
    }
    final config = latest.copyConfig();
    final servers = automationList(config['servers']);
    var server = servers.where((item) => item['id'] == 'netease').firstOrNull;
    if (server == null) {
      server = await repository.neteaseTemplate();
      servers.add(server);
    }
    server['enabled'] = true;
    config['servers'] = servers;
    await repository.saveAutomation(config);
    await repository.connectNetease();
    notice = '已连接。直接说想听什么，TA 会找歌并播放；可在权限中改为逐次确认。';
  });

  Future<void> disableNetease() => _mutate((repository) async {
    final config = (await _fresh(repository)).copyConfig();
    final servers = automationList(config['servers']);
    final server = servers.where((item) => item['id'] == 'netease').firstOrNull;
    if (server == null) return;
    server['enabled'] = false;
    config['servers'] = servers;
    await repository.saveAutomation(config);
    notice = '已停用网易云音乐连接，已保存的权限保留。';
  });

  Future<void> setToolsEnabled(bool enabled) => _mutate((repository) async {
    final config = (await _fresh(repository)).copyConfig();
    config['loop'] = {...automationMap(config['loop']), 'enabled': enabled};
    await repository.saveAutomation(config);
  });

  Future<void> setMusicPermission(String mode) => _mutate((repository) async {
    if (!{'ask', 'allow', 'off'}.contains(mode)) return;
    final latest = await _fresh(repository);
    final config = latest.copyConfig();
    final servers = automationList(config['servers']);
    final server = servers.where((item) => item['id'] == 'netease').firstOrNull;
    if (server == null || latest.neteaseTools.isEmpty) {
      throw const CompanionException('请先连接网易云音乐。');
    }
    final rules = automationMap(server['tools']);
    for (final tool in latest.neteaseTools) {
      final name = tool['name'] as String;
      rules[name] = {...automationMap(rules[name]), 'mode': mode};
    }
    server['tools'] = rules;
    config['servers'] = servers;
    await repository.saveAutomation(config);
    notice = '网易云操作权限已保存。';
  });

  Future<void> setPermission(String name, String mode) => _mutate((
    repository,
  ) async {
    if (!{'ask', 'allow', 'off'}.contains(mode)) return;
    final latest = await _fresh(repository);
    final config = latest.copyConfig();
    final servers = automationList(config['servers']);
    final server = servers.where((item) => item['id'] == 'netease').firstOrNull;
    if (server == null ||
        !latest.neteaseTools.any((item) => item['name'] == name)) {
      throw const CompanionException('工具列表已变化，请重新连接后再设置。');
    }
    final rules = automationMap(server['tools']);
    rules[name] = {...automationMap(rules[name]), 'mode': mode};
    server['tools'] = rules;
    config['servers'] = servers;
    await repository.saveAutomation(config);
    notice = '权限已保存。';
  });

  Future<void> decide(String id, String decision) => _mutate((
    repository,
  ) async {
    if (!{'approve', 'deny', 'resume'}.contains(decision)) return;
    final result = await repository.decideAutomation(id, decision);
    final continuationError = result['continuation_error'] as String?;
    notice =
        continuationError ?? (decision == 'deny' ? '已拒绝，操作没有执行。' : '操作状态已更新。');
    await onActionComplete();
  });

  Future<void> pickSong(String conversation, Map<String, dynamic> card) =>
      _mutate((repository) async {
        final result = await repository.pickMusic({
          'conversation_id': conversation,
          'search_action_id': card['search_action_id'],
          'song_id': card['id'],
          'request_id': DateTime.now().microsecondsSinceEpoch.toString(),
        });
        final operation = automationMap(result['operation']);
        if (operation['status'] != 'succeeded') {
          error = '播放结果暂未确认，请先查看网易云。';
        }
        await onActionComplete();
      });

  @override
  void dispose() {
    _disposed = true;
    _generation++;
    super.dispose();
  }
}
