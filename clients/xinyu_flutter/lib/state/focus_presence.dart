import 'package:flutter/foundation.dart';

import '../data/focus.dart';

/// Ephemeral interaction state for one focus session, never an attention score.
class FocusPresence extends ChangeNotifier {
  String? _sessionId, _phase;
  String? step, lastCompletedStep, response, error;
  bool pending = false, _disposed = false;
  int _generation = 0;
  int cue = 0;
  DateTime? _lastTouch;

  void sync(FocusSession? session, {bool force = false}) {
    final changed = _sessionId != session?.id;
    if (!force && !changed && _phase == session?.phase) return;
    _sessionId = session?.id;
    _phase = session?.phase;
    _lastTouch = null;
    if (changed || force) {
      step = null;
      lastCompletedStep = null;
    }
    clearReply();
  }

  bool touch() {
    final now = DateTime.now();
    if (_lastTouch != null &&
        now.difference(_lastTouch!).inMilliseconds < 1200) {
      return false;
    }
    _lastTouch = now;
    return true;
  }

  bool setStep(String value) {
    final text = value.trim();
    if (_sessionId == null ||
        !const {'focus', 'focus_paused'}.contains(_phase) ||
        text.isEmpty ||
        text.length > 160) {
      return false;
    }
    step = text;
    notifyListeners();
    return true;
  }

  bool completeStep() {
    if (step == null || !const {'focus', 'focus_paused'}.contains(_phase)) {
      return false;
    }
    lastCompletedStep = step;
    step = null;
    notifyListeners();
    return true;
  }

  void clearReply() {
    _generation++;
    response = error = null;
    pending = false;
    notifyListeners();
  }

  int beginReply() {
    clearReply();
    pending = true;
    cue++;
    notifyListeners();
    return _generation;
  }

  bool accepts(int ticket) => !_disposed && ticket == _generation;

  void retryReply(int ticket) {
    if (!accepts(ticket)) return;
    pending = true;
    error = null;
    notifyListeners();
  }

  void finishReply(int ticket, {String? text, String? failure}) {
    if (!accepts(ticket)) return;
    pending = false;
    response = text;
    error = failure;
    notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
