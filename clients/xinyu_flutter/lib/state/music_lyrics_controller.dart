import 'dart:async';

import 'package:flutter/foundation.dart';

import '../data/local_repository.dart';
import '../data/user_problem.dart';

class MusicLyricsController extends ChangeNotifier {
  MusicLyricsController(this.connection);
  final LocalRepository? Function() connection;
  Map<String, dynamic> value = {};
  Map<String, dynamic>? _request;
  String? error;
  bool loading = false, _disposed = false;
  int _revision = 0;

  void sync(Map<String, dynamic>? session) {
    final media = session?['media'];
    final key = media is Map && media['available'] == true
        ? media['track_key'] as String?
        : null;
    if (key == _request?['track_key'] &&
        session?['id'] == _request?['session_id']) {
      return;
    }
    _revision++;
    value = {};
    error = null;
    loading = false;
    _request = key == null
        ? null
        : {
            'conversation_id': session!['conversation_id'],
            'session_id': session['id'],
            'track_key': key,
          };
    if (_request != null) unawaited(fetch());
  }

  Future<void> fetch({String? songId}) async {
    final request = _request;
    if (request == null || _disposed) return;
    final revision = ++_revision;
    loading = true;
    error = null;
    notifyListeners();
    try {
      final result = await connection()?.musicLyrics({
        ...request,
        'song_id': ?songId,
      });
      if (_disposed || revision != _revision || result == null) return;
      if (result['track_key'] != request['track_key']) return;
      value = result;
    } catch (e) {
      if (!_disposed && revision == _revision) {
        error = userProblemMessage(e, fallback: '歌词暂时没取到，可以稍后重试。');
      }
    } finally {
      if (!_disposed && revision == _revision) {
        loading = false;
        notifyListeners();
      }
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _revision++;
    super.dispose();
  }
}
