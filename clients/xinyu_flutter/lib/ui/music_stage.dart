import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../state/music_controller.dart';
import 'music_lyrics.dart';
import 'music_record.dart';
import 'music_style.dart';
import 'music_transport.dart';

class MusicStage extends StatefulWidget {
  const MusicStage({
    super.key,
    required this.music,
    required this.wide,
    required this.height,
    this.onQuote,
    this.separateLyrics = false,
  });
  final MusicController music;
  final bool wide, separateLyrics;
  final double height;
  final ValueChanged<String>? onQuote;
  @override
  State<MusicStage> createState() => _MusicStageState();
}

class _MusicStageState extends State<MusicStage> {
  bool lyricsOpen = false;
  @override
  Widget build(BuildContext context) {
    final music = widget.music;
    final title = music.available
        ? music.media['title'] as String? ?? '歌曲信息待更新'
        : '等一首想听的歌';
    final artist = music.available
        ? music.media['artist'] as String? ?? ''
        : '打开网易云，播放你喜欢的歌';
    final cover = music.lyrics.value['cover_url'] as String?;
    final recordSize = widget.wide ? 260.0 : 128.0;
    return Column(
      children: [
        Text(
          title,
          textAlign: TextAlign.center,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: widget.wide ? 26 : 21,
            height: 1.4,
            fontWeight: FontWeight.w500,
            color: MusicStyle.ink,
          ),
        ),
        const SizedBox(height: 4),
        Text(
          artist,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          textAlign: TextAlign.center,
          style: MusicStyle.note,
        ),
        if (!widget.separateLyrics)
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              for (final item in [(false, '唱片'), (true, '歌词')])
                TextButton(
                  key: ValueKey(
                    item.$1 ? 'music-lyrics-tab' : 'music-record-tab',
                  ),
                  onPressed: () => setState(() => lyricsOpen = item.$1),
                  child: Text(
                    item.$2,
                    style: TextStyle(
                      fontSize: 14,
                      color: lyricsOpen == item.$1
                          ? MusicStyle.ink
                          : MusicStyle.muted,
                      fontWeight: lyricsOpen == item.$1
                          ? FontWeight.w500
                          : FontWeight.w400,
                      decoration: lyricsOpen == item.$1
                          ? TextDecoration.underline
                          : null,
                    ),
                  ),
                ),
            ],
          )
        else
          const SizedBox(height: 40),
        if (lyricsOpen && !widget.separateLyrics)
          SizedBox(
            height: math.max(180, widget.height - 260),
            child: MusicLyricsPane(
              music: music,
              onQuote: widget.onQuote,
              heading: false,
            ),
          )
        else ...[
          LayoutBuilder(
            builder: (_, box) => MusicRecord(
              size: math.min(box.maxWidth - 16, recordSize),
              playing: music.visualPlaying,
              cover: cover,
            ),
          ),
          if (!widget.separateLyrics) ...[
            const SizedBox(height: 8),
            ConstrainedBox(
              constraints: const BoxConstraints(minHeight: 62),
              child: MusicLyrics(
                music: music,
                compact: true,
                onExpand: () => setState(() => lyricsOpen = true),
              ),
            ),
          ] else
            const SizedBox(height: 36),
        ],
        const SizedBox(height: 12),
        MusicTransport(music: music),
      ],
    );
  }
}

class MusicLyricsPane extends StatelessWidget {
  const MusicLyricsPane({
    super.key,
    required this.music,
    this.onQuote,
    this.heading = true,
  });
  final MusicController music;
  final ValueChanged<String>? onQuote;
  final bool heading;
  @override
  Widget build(BuildContext context) => Column(
    children: [
      Row(
        children: [
          Expanded(
            child: Text(
              heading ? '歌词' : '',
              style: const TextStyle(fontSize: 15),
            ),
          ),
          if ((music.lyrics.value['candidates'] as List? ?? []).isNotEmpty)
            IconButton(
              tooltip: '更换歌词版本',
              onPressed: () => chooseMusicLyrics(context, music),
              icon: const Icon(Icons.tune_rounded, size: 20),
            ),
        ],
      ),
      Expanded(
        child: MusicLyrics(music: music, onQuote: onQuote),
      ),
    ],
  );
}
