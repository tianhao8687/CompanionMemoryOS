import 'package:flutter/material.dart';

import '../state/music_controller.dart';
import 'music_style.dart';

Future<bool> showMusicLyricActions(
  BuildContext context,
  MusicController music,
  Map<String, dynamic> line,
  ValueChanged<String>? quote,
) async {
  final track = music.media['track_key'];
  final song = music.lyrics.value['song_id'];
  final time = line['time_ms'];
  final text = line['text'] as String;
  final action = await showModalBottomSheet<String>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (context) => SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.fromLTRB(24, 0, 24, 24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(text, style: const TextStyle(fontSize: 20, height: 1.6)),
            const SizedBox(height: 16),
            if (quote != null)
              ListTile(
                key: const Key('music-quote-lyric'),
                leading: const Icon(Icons.chat_bubble_outline_rounded),
                title: const Text('聊聊这句'),
                subtitle: const Text('放入输入框，由你决定何时发送'),
                onTap: () => Navigator.pop(context, 'quote'),
              ),
            if (time is num && music.lyrics.value['timed'] == true) ...[
              if (music.positionMs() == null)
                ListTile(
                  key: const Key('music-align-lyric'),
                  leading: const Icon(Icons.sync_rounded),
                  title: const Text('歌词从这句开始跟随'),
                  subtitle: const Text('听到这句时点一下；只校准歌词，不跳转音乐'),
                  onTap: () => Navigator.pop(context, 'align'),
                ),
              if (music.canSeek)
                ListTile(
                  key: const Key('music-seek-lyric'),
                  leading: const Icon(Icons.play_circle_outline_rounded),
                  title: const Text('歌曲播放到这里'),
                  onTap: () => Navigator.pop(context, 'seek'),
                ),
            ],
            const SizedBox(height: 8),
            const Text(
              '分享歌词可以一起聊文字和感受；AI 当前没有接收到歌曲音频。',
              style: MusicStyle.note,
            ),
          ],
        ),
      ),
    ),
  );
  if (!music.available ||
      track != music.media['track_key'] ||
      song != music.lyrics.value['song_id']) {
    return false;
  }
  if (action == 'quote') {
    quote?.call(
      '《${music.media['title']}》（${music.media['artist']}）里这句歌词：\n“$text”\n',
    );
  }
  if (action == 'align' && time is num) music.alignLyrics(time.toInt());
  if (action == 'seek' && time is num && track is String) {
    await music.seek(time.toInt(), track);
  }
  return action == 'align' || action == 'seek';
}
