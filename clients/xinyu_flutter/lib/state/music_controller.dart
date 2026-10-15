import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart';

import '../data/automation.dart';
import '../data/local_repository.dart';
import '../data/models.dart';
import '../data/user_problem.dart';
import 'music_lyrics_controller.dart';
import 'music_lyric_clock.dart';

class MusicController extends ChangeNotifier {
  MusicController(
    this.connection,
    this.conversation, {
    required this.composing,
    required this.onMessage,
  }) {
    lyrics = MusicLyricsController(connection)..addListener(_emit);
  }
  late final MusicLyricsController lyrics;
  final lyricClock = MusicLyricClock();
  String? _alignedSong;
  final LocalRepository? Function() connection;
  final String? Function() conversation;
  final bool Function() composing;
  final Future<void> Function() onMessage;
  Map<String, dynamic>? state;
  String? error;
  bool busy = false, _polling = false, _disposed = false, _foreground = true;
  bool _composingHere = false, _reportedComposing = false;
  bool get composingHere => _composingHere;
  set composingHere(bool value) {
    _composingHere = value;
    updateComposing();
  }

  void updateComposing() {
    final value = composingHere || composing();
    if (!active || value == _reportedComposing || !_foreground) return;
    _reportedComposing = value;
    try {
      unawaited(
        connection()
            ?.music(_request('activity'))
            .catchError((Object _) => <String, dynamic>{}),
      );
    } catch (_) {
      // A failed presence update never sends or repeats a chat message.
    }
  }

  int _generation = 0, _operation = 0;
  Timer? _timer;
  bool get active => state?['active'] == true;
  bool get quiet => state?['quiet'] == true;
  Map<String, dynamic> get media => automationMap(state?['media']);
  bool get available => active && media['available'] == true;
  bool get playing => available && media['playback'] == 'playing';
  bool get visualPlaying => playing && _foreground;
  bool get canSeek =>
      available &&
      automationMap(media['controls'])['seek'] == true &&
      media['duration_ms'] is num &&
      (media['duration_ms'] as num) > 0;
  int? get durationMs {
    final value =
        media['duration_ms'] ??
        automationMap(lyrics.value['song'])['duration_ms'];
    return value is num && value > 0 ? value.toInt() : null;
  }

  int? lyricsPositionMs() {
    final native = positionMs();
    if (native != null) return native;
    if (!available || !_foreground || _alignedSong != lyrics.value['song_id']) {
      return null;
    }
    final value = lyricClock.position;
    return value?.clamp(0, durationMs ?? 86400000);
  }

  bool get lyricsCalibrated =>
      positionMs() == null && lyricsPositionMs() != null;

  void alignLyrics(int milliseconds) {
    if (!available || lyrics.value['timed'] != true) return;
    lyricClock.observe('${state?['id']}:${media['track_key']}', playing);
    lyricClock.align(milliseconds);
    _alignedSong = lyrics.value['song_id'] as String?;
    _emit();
  }

  Future<void> seek(int milliseconds, String trackKey) =>
      act('seek', position: milliseconds, trackKey: trackKey);

  int? positionMs([DateTime? at]) {
    final position = media['position_ms'];
    final duration = media['duration_ms'];
    final sampled = media['sampled_at_ms'];
    if (!available ||
        position is! num ||
        duration is! num ||
        duration <= 0 ||
        sampled is! num ||
        position < 0) {
      return null;
    }
    final elapsed = (at ?? DateTime.now()).millisecondsSinceEpoch - sampled;
    if (elapsed < -5000 || elapsed > 20000) return null;
    final rate = media['playback_rate'] as num? ?? 1;
    final advance = visualPlaying ? max(0, elapsed) * rate : 0;
    return (position + advance).clamp(0, duration).toInt();
  }

  void _accept(Map<String, dynamic>? value) {
    state = value;
    lyricClock.observe(
      available ? '${state?['id']}:${media['track_key']}' : null,
      playing,
    );
    lyrics.sync(value);
  }

  void _emit() {
    if (!_disposed) notifyListeners();
  }

  void reset() {
    _generation++;
    _timer?.cancel();
    _accept(null);
    error = null;
    busy = _polling = false;
    _emit();
  }

  void setForeground(bool value) {
    _operation++;
    _foreground = value;
    if (!value) lyricClock.clear();
    _emit();
    _timer?.cancel();
    if (!active) return;
    if (value) {
      unawaited(poll());
      _schedule();
    } else {
      try {
        unawaited(
          connection()
              ?.music(_request('suspend'))
              .catchError((Object _) => <String, dynamic>{}),
        );
      } catch (_) {
        // The server's heartbeat also expires after 30 seconds.
      }
    }
  }

  Map<String, dynamic> _request(String action, {bool? silent}) => {
    'conversation_id': state?['conversation_id'] ?? conversation(),
    'session_id': state?['id'] ?? '',
    'request_id':
        '${DateTime.now().microsecondsSinceEpoch}-${Random.secure().nextInt(1 << 30)}',
    'action': action,
    'quiet': silent ?? quiet,
    'composing': composingHere || composing(),
  };

  Future<void> act(
    String action, {
    bool? silent,
    int? position,
    String? trackKey,
  }) async {
    if (busy || _disposed) return;
    final generation = _generation;
    _operation++;
    busy = true;
    error = null;
    _emit();
    try {
      final repository = connection();
      if (repository == null || conversation() == null) {
        throw const CompanionException('请先打开本机数据并连接网易云音乐。');
      }
      final result = await repository.music({
        ..._request(action, silent: silent),
        'position_ms': ?position,
        'track_key': ?trackKey,
      });
      if (_disposed || generation != _generation) return;
      _accept(result['active'] == true ? result : null);
      final operation = automationMap(result['operation']);
      if (operation.isNotEmpty && operation['status'] != 'succeeded') {
        final data = automationMap(operation['data']);
        error =
            data['message'] as String? ??
            operation['message'] as String? ??
            '播放结果尚未确认，请查看网易云。';
      }
      _schedule();
    } catch (e) {
      if (!_disposed && generation == _generation) {
        _accept({...?state, 'media': <String, dynamic>{}});
        error = userProblemMessage(e, fallback: '音乐连接暂不可用，请稍后重试。');
      }
    } finally {
      if (!_disposed && generation == _generation) {
        busy = false;
        _emit();
      }
    }
  }

  void _schedule() {
    _timer?.cancel();
    if (active && _foreground) {
      _timer = Timer.periodic(
        const Duration(seconds: 2),
        (_) => unawaited(poll()),
      );
    }
  }

  Future<void> poll() async {
    if (_disposed || _polling || busy || !active || !_foreground) return;
    final generation = _generation;
    final operation = _operation;
    _polling = true;
    try {
      final reply = state?['reply_id'];
      final result = await connection()?.music(_request('poll'));
      if (_disposed ||
          generation != _generation ||
          operation != _operation ||
          result == null ||
          !_foreground) {
        return;
      }
      _accept(result['active'] == true ? result : null);
      error = null;
      if (result['reply_id'] != null && result['reply_id'] != reply) {
        await onMessage();
      }
      _emit();
    } catch (_) {
      if (!_disposed && generation == _generation && operation == _operation) {
        // Clear stale playback instead of showing an old track as live.
        _accept({...?state, 'media': <String, dynamic>{}});
        error = '播放状态暂未同步，稍后会自动更新。';
        _emit();
      }
    } finally {
      if (generation == _generation) _polling = false;
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _generation++;
    _timer?.cancel();
    lyrics.removeListener(_emit);
    lyrics.dispose();
    super.dispose();
  }
}
