import 'dart:async';

import 'package:flutter/material.dart';

import '../data/automation.dart';
import '../state/music_controller.dart';
import 'music_style.dart';

class MusicTransport extends StatefulWidget {
  const MusicTransport({super.key, required this.music});
  final MusicController music;
  @override
  State<MusicTransport> createState() => _MusicTransportState();
}

class _MusicTransportState extends State<MusicTransport> {
  Timer? timer;
  int? position;
  double? dragging;
  String? dragTrack;
  @override
  void initState() {
    super.initState();
    timer = Timer.periodic(const Duration(milliseconds: 500), (_) {
      final next = widget.music.positionMs();
      if (mounted && next != position) setState(() => position = next);
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  String _time(num? ms) => ms == null
      ? '--:--'
      : '${ms ~/ 60000}:${((ms ~/ 1000) % 60).toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final music = widget.music;
    final controls = automationMap(music.media['controls']);
    final elapsed = music.positionMs(), duration = music.durationMs;
    return Column(
      children: [
        Semantics(
          label: '播放进度',
          value: elapsed == null
              ? '网易云暂未提供'
              : '${_time(elapsed)} / ${_time(duration)}',
          child: Row(
            children: [
              Text(
                _time(dragging ?? elapsed),
                style: MusicStyle.note.copyWith(fontSize: 12),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: music.canSeek && duration != null
                    ? SliderTheme(
                        data: SliderTheme.of(context).copyWith(
                          trackHeight: 2,
                          thumbShape: const RoundSliderThumbShape(
                            enabledThumbRadius: 5,
                          ),
                          overlayShape: const RoundSliderOverlayShape(
                            overlayRadius: 16,
                          ),
                          activeTrackColor: MusicStyle.accent,
                          inactiveTrackColor: MusicStyle.line,
                          thumbColor: MusicStyle.accent,
                        ),
                        child: Slider(
                          key: const Key('music-seek'),
                          value: (dragging ?? elapsed?.toDouble() ?? 0).clamp(
                            0,
                            duration.toDouble(),
                          ),
                          max: duration.toDouble(),
                          label: _time(dragging ?? elapsed),
                          semanticFormatterCallback: (value) => _time(value),
                          onChanged: music.busy
                              ? null
                              : (value) => setState(() {
                                  dragTrack ??=
                                      music.media['track_key'] as String?;
                                  dragging = value;
                                }),
                          onChangeEnd: (value) {
                            final track = dragTrack;
                            setState(() {
                              dragging = null;
                              dragTrack = null;
                            });
                            if (track != null) {
                              unawaited(music.seek(value.round(), track));
                            }
                          },
                        ),
                      )
                    : ClipRRect(
                        borderRadius: BorderRadius.circular(2),
                        child: LinearProgressIndicator(
                          value:
                              elapsed != null &&
                                  duration != null &&
                                  duration > 0
                              ? elapsed / duration
                              : 0,
                          minHeight: 2,
                          backgroundColor: MusicStyle.line,
                          color: MusicStyle.accent,
                        ),
                      ),
              ),
              const SizedBox(width: 12),
              Text(
                _time(duration),
                style: MusicStyle.note.copyWith(fontSize: 12),
              ),
            ],
          ),
        ),
        if (music.available && !music.canSeek)
          Padding(
            padding: const EdgeInsets.only(top: 8),
            child: Text(
              '播放进度请在网易云内调整',
              style: MusicStyle.note.copyWith(fontSize: 12),
            ),
          ),
        const SizedBox(height: 8),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            for (final item in [
              ('previous', '上一首', Icons.skip_previous_rounded),
              (
                music.playing ? 'pause' : 'play',
                music.playing ? '暂停' : '播放',
                music.playing ? Icons.pause_rounded : Icons.play_arrow_rounded,
              ),
              ('next', '下一首', Icons.skip_next_rounded),
            ])
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                child: IconButton(
                  key: ValueKey('music-${item.$1}'),
                  tooltip: item.$2,
                  onPressed:
                      !music.available ||
                          music.busy ||
                          controls[item.$1] != true
                      ? null
                      : () => music.act(item.$1),
                  style: IconButton.styleFrom(
                    foregroundColor: MusicStyle.ink,
                    disabledForegroundColor: MusicStyle.muted.withValues(
                      alpha: .4,
                    ),
                    fixedSize: const Size.square(56),
                    minimumSize: const Size.square(56),
                    maximumSize: const Size.square(56),
                    padding: EdgeInsets.zero,
                    alignment: Alignment.center,
                    iconSize: 32,
                    side: item.$1 == 'play' || item.$1 == 'pause'
                        ? const BorderSide(color: Color(0x99ffffff), width: 1.2)
                        : null,
                  ),
                  icon: Icon(item.$3),
                ),
              ),
          ],
        ),
      ],
    );
  }
}
