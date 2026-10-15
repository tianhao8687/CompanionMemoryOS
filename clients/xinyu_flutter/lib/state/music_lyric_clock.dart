/// A user-aligned lyric clock. It never supplies the player's seek position.
class MusicLyricClock {
  MusicLyricClock({int Function()? milliseconds}) {
    final watch = Stopwatch()..start();
    _now = milliseconds ?? () => watch.elapsedMilliseconds;
  }
  late final int Function() _now;
  String? _track;
  int? _anchor;
  int _sample = 0;
  bool _playing = false;

  int? get position => _anchor == null
      ? null
      : _anchor! + (_playing ? (_now() - _sample).clamp(0, 86400000) : 0);

  void observe(String? track, bool playing) {
    final current = position;
    _anchor = track != null && track == _track ? current : null;
    _track = track;
    _playing = playing;
    _sample = _now();
  }

  void align(int milliseconds) {
    if (_track == null || milliseconds < 0 || milliseconds > 86400000) return;
    _anchor = milliseconds;
    _sample = _now();
  }

  void clear() {
    _anchor = null;
  }
}
