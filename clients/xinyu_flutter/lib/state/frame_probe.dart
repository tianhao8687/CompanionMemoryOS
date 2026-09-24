import 'dart:math';
import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/scheduler.dart';

class FrameProbe extends ChangeNotifier {
  FrameProbe() {
    SchedulerBinding.instance.addTimingsCallback(_record);
    _timer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (visible && _dirty) {
        _dirty = false;
        notifyListeners();
      }
    });
  }
  final List<FrameTiming> _frames = [];
  bool visible = false;
  late final Timer _timer;
  bool _dirty = false;
  void _record(List<FrameTiming> batch) {
    _frames.addAll(batch);
    if (_frames.length > 600) _frames.removeRange(0, _frames.length - 600);
    _dirty = true;
  }

  void toggle() {
    visible = !visible;
    notifyListeners();
  }

  void reset() {
    _frames.clear();
    notifyListeners();
  }

  Map<String, Object> summary() {
    final build =
        _frames.map((f) => f.buildDuration.inMicroseconds / 1000).toList()
          ..sort();
    final raster =
        _frames.map((f) => f.rasterDuration.inMicroseconds / 1000).toList()
          ..sort();
    double p95(List<double> values) =>
        values.isEmpty ? 0 : values[(values.length * .95).ceil() - 1];
    return {
      'frames': _frames.length,
      'build_p95_ms': p95(build),
      'raster_p95_ms': p95(raster),
      'over_16_67_ms': _frames
          .where(
            (f) =>
                max(
                  f.buildDuration.inMicroseconds,
                  f.rasterDuration.inMicroseconds,
                ) >
                16667,
          )
          .length,
      'mode': kReleaseMode
          ? 'release'
          : kProfileMode
          ? 'profile'
          : 'debug',
    };
  }

  @override
  void dispose() {
    _timer.cancel();
    SchedulerBinding.instance.removeTimingsCallback(_record);
    super.dispose();
  }
}
