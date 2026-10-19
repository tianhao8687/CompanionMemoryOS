import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

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

  Future<void> connectPhone() => _mutate((repository) async {
    final latest = await _fresh(repository);
    if (latest.phone['supported'] != true) {
      throw const CompanionException('手机能力需要 Android 9 或更高版本。');
    }
    final config = latest.copyConfig();
    final servers = automationList(config['servers']);
    var server = servers.where((item) => item['id'] == 'droid').firstOrNull;
    if (server == null) {
      server = await repository.phoneTemplate();
      servers.add(server);
    }
    server['enabled'] = true;
    config['servers'] = servers;
    await repository.saveAutomation(config);
    await repository.connectPhone();
    notice = '手机能力已连接。基础操作默认先确认，界面操作需单独开启。';
  });

  Future<void> disablePhone() => _mutate((repository) async {
    final config = (await _fresh(repository)).copyConfig();
    final servers = automationList(config['servers']);
    final server = servers.where((item) => item['id'] == 'droid').firstOrNull;
    if (server == null) return;
    server['enabled'] = false;
    config['servers'] = servers;
    await repository.saveAutomation(config);
    notice = '已停用手机能力，已保存的权限保留。';
  });

  Future<void> setPhoneGroupPermission(String groupId, String mode) => _mutate((
    repository,
  ) async {
    if (!{'ask', 'allow', 'off'}.contains(mode)) return;
    if (groupId == 'chat_notifications' && mode == 'allow') mode = 'ask';
    final latest = await _fresh(repository);
    final group = automationList(latest.phone['groups'])
        .where((item) => item['id'] == groupId)
        .firstOrNull;
    final config = latest.copyConfig();
    final servers = automationList(config['servers']);
    final server = servers.where((item) => item['id'] == 'droid').firstOrNull;
    if (server == null || group == null || latest.phoneTools.isEmpty) {
      throw const CompanionException('请先连接手机能力。');
    }
    final available = latest.phoneTools.map((tool) => tool['name']).toSet();
    final rules = automationMap(server['tools']);
    for (final name in (group['tools'] as List).whereType<String>().where(
      available.contains,
    )) {
      rules[name] = {...automationMap(rules[name]), 'mode': mode};
    }
    server['tools'] = rules;
    config['servers'] = servers;
    if (groupId == 'haptics' && mode != 'allow') {
      config['reply_haptics_enabled'] = false;
    }
    await repository.saveAutomation(config);
    notice = '手机能力权限已保存。';
  });

  Future<void> setReplyHaptics(bool enabled) => _mutate((repository) async {
    final latest = await _fresh(repository);
    final config = latest.copyConfig();
    if (enabled) {
      final servers = automationList(config['servers']);
      final server = servers.where((item) => item['id'] == 'droid').firstOrNull;
      final available = latest.phoneTools.map((tool) => tool['name']).toSet();
      if (server == null ||
          server['enabled'] != true ||
          !available.containsAll(['vibrate_pattern', 'cancel_vibration'])) {
        throw const CompanionException('请先连接支持触感的手机能力。');
      }
      final rules = automationMap(server['tools']);
      for (final name in ['vibrate_pattern', 'cancel_vibration']) {
        rules[name] = {...automationMap(rules[name]), 'mode': 'allow'};
      }
      server['tools'] = rules;
      config['servers'] = servers;
      config['loop'] = {...automationMap(config['loop']), 'enabled': true};
    }
    config['reply_haptics_enabled'] = enabled;
    await repository.saveAutomation(config);
    notice = enabled ? '已开启。TA 会在情感浓烈的回复里偶尔用短拍表达，不需要逐次确认。' : '已关闭随回复触感。';
  });

  Future<void> openPhonePermission(String permission) async {
    if (!{
      'accessibility',
      'dnd',
      'write_settings',
      'overlay',
      'chat_notifications',
    }.contains(permission)) {
      return;
    }
    try {
      await const MethodChannel('xinyu/phone').invokeMethod<void>(
        'openPermissionSettings',
        {'permission': permission},
      );
    } catch (_) {
      error = '无法打开系统权限页面，请在手机设置中为心隅授权。';
      _emit();
    }
  }

  Future<void> setPhoneComfort(String field, bool value) => _mutate((
    repository,
  ) async {
    if (!{'enabled', 'media', 'screen', 'interruptions'}.contains(field)) {
      return;
    }
    final latest = await _fresh(repository);
    final config = latest.copyConfig();
    final servers = automationList(config['servers']);
    final server = servers.where((item) => item['id'] == 'droid').firstOrNull;
    if (server == null ||
        server['enabled'] != true ||
        latest.phoneTools.isEmpty) {
      throw const CompanionException('请先连接手机能力。');
    }
    final comfort = <String, dynamic>{
      'enabled': false,
      'media': true,
      'screen': false,
      'interruptions': false,
      ...automationMap(config['phone_comfort']),
      field: value,
    };
    if (field == 'enabled' && value) comfort['paused_until'] = null;
    const channelTools = {
      'media': ['get_settings', 'set_volume'],
      'screen': [
        'get_settings',
        'set_brightness',
        'get_light_level',
        'get_proximity',
      ],
      'interruptions': ['get_dnd_status', 'set_dnd_mode'],
    };
    if (value && comfort['enabled'] == true) {
      final rules = automationMap(server['tools']);
      final available = latest.phoneTools.map((tool) => tool['name']).toSet();
      for (final entry in channelTools.entries) {
        if (comfort[entry.key] != true ||
            (field != 'enabled' && field != entry.key)) {
          continue;
        }
        for (final name in entry.value) {
          if (!available.contains(name)) {
            throw const CompanionException('手机能力已更新，请重新连接。');
          }
          rules[name] = {...automationMap(rules[name]), 'mode': 'allow'};
        }
      }
      server['tools'] = rules;
      config['loop'] = {...automationMap(config['loop']), 'enabled': true};
    }
    config['servers'] = servers;
    config['phone_comfort'] = comfort;
    await repository.saveAutomation(config);
    notice = comfort['enabled'] == true
        ? '已保存陪伴范围。TA 会结合聊天判断，不会每次表达情绪都操作。'
        : '已停止主动调整。已有调整可用下方按钮恢复。';
  });

  Future<void> restorePhoneComfort() => _mutate((repository) async {
    final result = await repository.restorePhoneComfort();
    notice = result['verified'] == true
        ? '已核对恢复；你手动改过的设置保持现状。'
        : '仍有设置未确认恢复，请检查手机权限和操作记录。';
  });

  Future<void> setPhoneComfortCooldown(int minutes) =>
      _mutate((repository) async {
        if (![1, 3, 5].contains(minutes)) return;
        final config = (await _fresh(repository)).copyConfig();
        config['phone_comfort'] = {
          ...automationMap(config['phone_comfort']),
          'cooldown_minutes': minutes,
        };
        await repository.saveAutomation(config);
        notice = '联动至少间隔 $minutes 分钟；到点不会自动操作。';
      });

  Future<void> controlPhoneComfort(String action) => _mutate((
    repository,
  ) async {
    if (!{'pause', 'resume', 'keep'}.contains(action)) return;
    final ids = action == 'keep'
        ? automationList(state?.phoneComfort['active'])
              .map((row) => row['action_id'])
              .whereType<String>()
              .toSet()
              .toList()
        : <String>[];
    final result = await repository.controlPhoneComfort(action, actionIds: ids);
    notice = result['message'] as String?;
  });

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
