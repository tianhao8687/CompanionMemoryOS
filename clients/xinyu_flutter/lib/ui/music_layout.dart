import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../state/companion_controller.dart';
import 'music_companion.dart';
import 'music_stage.dart';
import 'music_style.dart';

class MusicListeningLayout extends StatelessWidget {
  const MusicListeningLayout({
    super.key,
    required this.controller,
    required this.input,
    required this.focus,
    required this.send,
    required this.connect,
    required this.quote,
  });
  final CompanionController controller;
  final TextEditingController input;
  final FocusNode focus;
  final VoidCallback send, connect;
  final ValueChanged<String> quote;

  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, box) {
      final desktop = box.maxWidth >= 900;
      final threeColumns =
          box.maxWidth >= 1180 &&
          MediaQuery.textScalerOf(context).scale(16) <= 22;
      final music = controller.music;
      final companion = MusicCompanionPanel(
        controller: controller,
        input: input,
        focus: focus,
        send: send,
      );
      Widget player(double height) => SingleChildScrollView(
        key: const Key('music-scroll'),
        padding: EdgeInsets.symmetric(
          horizontal: 12,
          vertical: desktop ? 12 : 4,
        ),
        child: Column(
          children: [
            MusicStage(
              music: music,
              wide: desktop,
              height: height,
              separateLyrics: threeColumns,
              onQuote: quote,
            ),
            MusicConnectionStatus(controller: controller, connect: connect),
          ],
        ),
      );
      if (desktop) {
        return Padding(
          padding: const EdgeInsets.fromLTRB(28, 24, 28, 32),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Expanded(flex: 10, child: player(box.maxHeight - 56)),
              if (threeColumns) ...[
                const SizedBox(width: 24),
                Expanded(
                  flex: 11,
                  child: Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: MusicLyricsPane(music: music, onQuote: quote),
                  ),
                ),
              ],
              const SizedBox(width: 28),
              SizedBox(
                width: threeColumns ? 344 : math.min(380, box.maxWidth * .44),
                child: companion,
              ),
            ],
          ),
        );
      }
      final compact =
          MediaQuery.viewInsetsOf(context).bottom > 0 || box.maxHeight < 400;
      return Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
        child: Column(
          children: [
            if (compact)
              SizedBox(
                height: 48,
                child: Row(
                  children: [
                    const Icon(Icons.music_note_rounded, size: 20),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        music.media['title'] as String? ?? '一起听',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: MusicStyle.note,
                      ),
                    ),
                  ],
                ),
              )
            else
              Expanded(child: player(box.maxHeight * .62)),
            const SizedBox(height: 12),
            if (compact)
              Expanded(child: companion)
            else
              SizedBox(
                height: (box.maxHeight * .40).clamp(260, 340),
                child: companion,
              ),
          ],
        ),
      );
    },
  );
}

class MusicConnectionStatus extends StatelessWidget {
  const MusicConnectionStatus({
    super.key,
    required this.controller,
    required this.connect,
  });
  final CompanionController controller;
  final VoidCallback connect;
  @override
  Widget build(BuildContext context) {
    final music = controller.music;
    return Column(
      children: [
        if (!music.available) ...[
          const SizedBox(height: 16),
          Text(
            music.media['message'] as String? ?? '请先在网易云中播放一首歌。',
            style: MusicStyle.note,
            textAlign: TextAlign.center,
          ),
          TextButton(
            onPressed: music.busy ? null : connect,
            child: const Text('检查网易云连接'),
          ),
          if (defaultTargetPlatform == TargetPlatform.android &&
              music.media['permission'] == false)
            TextButton(
              onPressed: () async {
                try {
                  await const MethodChannel('xinyu/music')
                      .invokeMethod('openPermissionSettings');
                } catch (_) {
                  controller.reportProblem('请在手机系统设置中开启心隅的通知使用权。');
                }
              },
              child: const Text('开启媒体控制权限'),
            ),
        ],
        if (music.error != null)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Semantics(
              liveRegion: true,
              child: Text(music.error!, style: MusicStyle.note),
            ),
          ),
      ],
    );
  }
}
