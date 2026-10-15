import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart';

import '../data/focus.dart';
import '../data/local_repository.dart';
import '../data/models.dart';
import 'focus_presence.dart';

/// All surfaces observe this projection of the one server clock.
class FocusController extends ChangeNotifier {
  FocusController(this.connection, this.conversation);
  final LocalRepository? Function() connection;
  final String? Function() conversation;
  FocusSession? session;
  List<Map<String, dynamic>> history = [];
  Map<String, dynamic> preferences = {
    'focus_sound': 'silent',
    'focus_notice': 'once',
  };
  final announcement = ValueNotifier<String?>(null);
  final presence = FocusPresence();
  final _noticeClaims = <String>{};
  String? error;
  bool busy = false, enabled = false;
  bool _disposed = false, _fetching = false, _foreground = true;
  int _generation = 0;
  double _offset = 0;
  Timer? _timer;
  DateTime _lastFetch = DateTime.fromMillisecondsSinceEpoch(0);
  Map<String, dynamic>? _startRequest;
  final _random = Random.secure();
  String requestId() => List.generate(
    16,
    (_) => _random.nextInt(256).toRadixString(16).padLeft(2, '0'),
  ).join();
  double get now => DateTime.now().millisecondsSinceEpoch / 1000 + _offset;
  int get seconds => max(
    0,
    (session?.deadline == null
            ? session?.remaining ?? 0
            : session!.deadline! - now)
        .ceil(),
  );

  void _emit() {
    if (!_disposed) notifyListeners();
  }

  void connect(bool available) {
    _timer?.cancel();
    _generation++;
    enabled = available;
    session = null;
    presence.sync(null, force: true);
    history = [];
    error = null;
    busy = false;
    _startRequest = null;
    _noticeClaims.clear();
    announcement.value = null;
    _lastFetch = DateTime.fromMillisecondsSinceEpoch(0);
    if (enabled) {
      unawaited(refresh());
      _timer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (!_foreground) return;
        if (session != null) _emit();
        final interval = session != null && !session!.settled ? 5 : 20;
        if (DateTime.now().difference(_lastFetch).inSeconds >= interval ||
            session?.deadline != null && seconds == 0) {
          unawaited(refresh());
        }
      });
    }
    _emit();
  }

  void setForeground(bool value) {
    _foreground = value;
    if (value) unawaited(refresh());
  }

  void _receive(Map<String, dynamic> value) {
    session = value['session'] is Map
        ? FocusSession(Map<String, dynamic>.from(value['session'] as Map))
        : null;
    presence.sync(session);
    _offset =
        (value['server_now'] as num).toDouble() -
        DateTime.now().millisecondsSinceEpoch / 1000;
    history = (value['history'] as List? ?? [])
        .map((v) => Map<String, dynamic>.from(v as Map))
        .toList();
    if (value['preferences'] is Map) {
      preferences = Map<String, dynamic>.from(value['preferences'] as Map);
    }
    unawaited(_checkNotice());
  }

  Future<void> _checkNotice() async {
    final current = session;
    if (_disposed ||
        !enabled ||
        !_foreground ||
        current == null ||
        preferences['focus_notice'] == 'off' ||
        !const {'focus_done', 'done'}.contains(current.phase) ||
        current.endedAt == null ||
        now - current.endedAt! > 120 ||
        current.noticeRevision == current.revision) {
      return;
    }
    final key = '${current.id}:${current.revision}';
    if (!_noticeClaims.add(key)) return;
    final repo = connection(), ticket = _generation;
    if (repo == null) {
      _noticeClaims.remove(key);
      return;
    }
    try {
      final claimed = await repo.claimFocusNotice(current.id, current.revision);
      if (claimed &&
          !_disposed &&
          enabled &&
          _foreground &&
          ticket == _generation &&
          identical(repo, connection()) &&
          session?.id == current.id &&
          session?.revision == current.revision &&
          preferences['focus_notice'] != 'off') {
        announcement.value = current.line;
      }
    } catch (_) {
      // A temporary connection failure can be retried on the next refresh.
      _noticeClaims.remove(key);
    }
  }

  Future<void> refresh() async {
    if (!enabled || _disposed || busy || _fetching) return;
    final repo = connection(), id = conversation(), ticket = _generation;
    if (repo == null || id == null) {
      return;
    }
    _fetching = true;
    _lastFetch = DateTime.now();
    try {
      final value = await repo.focus(id);
      if (!_disposed &&
          ticket == _generation &&
          identical(repo, connection())) {
        _receive(value);
        error = null;
        _emit();
      }
    } catch (_) {
      if (ticket == _generation) {
        error = '暂时连不上计时服务，恢复连接后会核对时间。';
        _emit();
      }
    } finally {
      _fetching = false;
    }
  }

  Future<bool> _change(
    Future<Map<String, dynamic>> Function(LocalRepository) run,
  ) async {
    if (busy || !enabled || _disposed) return false;
    final repo = connection();
    if (repo == null) return false;
    final ticket = ++_generation;
    busy = true;
    error = null;
    _emit();
    try {
      final result = await run(repo);
      if (_disposed ||
          ticket != _generation ||
          !identical(repo, connection())) {
        return false;
      }
      _receive(result);
      return true;
    } catch (e) {
      if (ticket == _generation) {
        try {
          final value = await repo.focus(conversation()!);
          if (!_disposed && ticket == _generation) _receive(value);
        } catch (_) {
          /* Keep the last confirmed state. */
        }
        error = e.toString();
      }
      return false;
    } finally {
      if (!_disposed && ticket == _generation) {
        busy = false;
        _emit();
      }
    }
  }

  Future<bool> start(String intention, int minutes, int rest) async {
    final id = conversation();
    if (id == null) return false;
    final values = {
      'conversation_id': id,
      'intention': intention.trim(),
      'focus_minutes': minutes,
      'rest_minutes': rest,
    };
    final previous = {...?_startRequest}..remove('request_id');
    if (!mapEquals(previous, values)) {
      _startRequest = {...values, 'request_id': requestId()};
    }
    final result = await _change((repo) => repo.startFocus(_startRequest!));
    if (result) _startRequest = null;
    return result;
  }

  Future<bool> act(String action) async {
    final current = session;
    if (current == null) return false;
    return _change(
      (repo) => repo.focusAction({
        'session_id': current.id,
        'revision': current.revision,
        'action': action,
      }),
    );
  }

  /// A shared pause is confirmed before entering a companionship activity.
  /// Leaving the activity never resumes a clock on the user's behalf.
  Future<bool> pauseForCompany() async {
    final current = session;
    final id = conversation();
    if (current == null || id == null || busy || !enabled || _disposed) {
      return false;
    }
    return _change((repo) async {
      final value = await repo.focus(id);
      final latest = value['session'];
      if (latest is! Map || latest['id'] != current.id) {
        throw const CompanionException('这段专注已切换，请按当前状态重新打开。');
      }
      if (const {
        'focus_paused',
        'rest_paused',
        'focus_done',
        'done',
        'ended',
      }.contains(latest['phase'])) {
        return value;
      }
      return repo.focusAction({
        'session_id': latest['id'],
        'revision': latest['revision'],
        'action': 'pause',
      });
    });
  }

  Future<bool> notice(bool enabled) => _change(
    (repo) => repo.focusPreference({
      'request_id': requestId(),
      'conversation_id': conversation(),
      'dimension': 'focus_notice',
      'value': enabled ? 'once' : 'off',
    }),
  );

  Future<void> saveProgress(
    String content,
    String request,
    String sessionId,
  ) async {
    final repo = connection();
    if (repo == null) throw StateError('请先连接本机引擎。');
    await repo.focusProgress({
      'request_id': request,
      'session_id': sessionId,
      'content': content.trim(),
    });
  }

  @override
  void dispose() {
    _disposed = true;
    _generation++;
    _timer?.cancel();
    announcement.dispose();
    presence.dispose();
    super.dispose();
  }
}
