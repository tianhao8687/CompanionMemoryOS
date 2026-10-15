import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart' show ScrollDirection;

import '../data/automation.dart';
import '../state/music_controller.dart';
import 'music_style.dart';
import 'music_lyric_actions.dart';

Future<void> chooseMusicLyrics(
  BuildContext context,
  MusicController music,
) async {
  final songs = automationList(music.lyrics.value['candidates']);
  final selected = await showModalBottomSheet<String>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (context) => SafeArea(
      child: SizedBox(
        height: math.min(MediaQuery.sizeOf(context).height * .65, 600),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(24, 4, 24, 16),
              child: Text(
                '选择正在听的版本',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w500),
              ),
            ),
            Expanded(
              child: ListView.builder(
                itemCount: songs.length,
                itemBuilder: (context, i) {
                  final song = songs[i];
                  return ListTile(
                    title: Text(song['name'] as String? ?? ''),
                    subtitle: Text(
                      '${(song['artists'] as List? ?? []).join(' / ')} · ${song['album'] ?? ''}',
                    ),
                    trailing: const Icon(Icons.chevron_right_rounded),
                    onTap: () => Navigator.pop(context, song['id'] as String),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    ),
  );
  if (selected != null) await music.lyrics.fetch(songId: selected);
}

class MusicLyrics extends StatefulWidget {
  const MusicLyrics({
    super.key,
    required this.music,
    this.compact = false,
    this.onExpand,
    this.onQuote,
  });
  final MusicController music;
  final bool compact;
  final VoidCallback? onExpand;
  final ValueChanged<String>? onQuote;
  @override
  State<MusicLyrics> createState() => _MusicLyricsState();
}

class _MusicLyricsState extends State<MusicLyrics> {
  final scroll = ScrollController();
  final keys = <int, GlobalKey>{};
  Timer? timer;
  int current = -1;
  bool following = true;
  Object? track;
  List<Map<String, dynamic>> get lines =>
      automationList(widget.music.lyrics.value['lines']);

  @override
  void initState() {
    super.initState();
    timer = Timer.periodic(const Duration(milliseconds: 400), (_) => _tick());
  }

  @override
  void didUpdateWidget(MusicLyrics oldWidget) {
    super.didUpdateWidget(oldWidget);
    final next = widget.music.lyrics.value['song_id'];
    if (track != next) {
      track = next;
      current = -1;
      following = true;
      keys.clear();
      if (scroll.hasClients) scroll.jumpTo(0);
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _tick();
    });
  }

  void _tick() {
    final position = widget.music.lyricsPositionMs();
    final next = position == null
        ? -1
        : lines.lastIndexWhere(
            (line) =>
                line['time_ms'] is num && (line['time_ms'] as num) <= position,
          );
    if (!mounted || next == current) return;
    setState(() => current = next);
    _follow();
  }

  void _follow() {
    if (!following || widget.compact || current < 0) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !scroll.hasClients) return;
      final target = keys[current]?.currentContext?.findRenderObject();
      if (target != null) {
        scroll.position.ensureVisible(
          target,
          alignment: .45,
          duration: Duration(
            milliseconds: MediaQuery.disableAnimationsOf(context) ? 0 : 350,
          ),
          curve: Curves.easeOutCubic,
        );
      }
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final music = widget.music, lyrics = music.lyrics;
    if (lyrics.loading) {
      return const Center(child: Text('正在找歌词…', style: MusicStyle.note));
    }
    if (lyrics.error != null) {
      return Center(
        child: TextButton(
          onPressed: () => lyrics.fetch(),
          child: Text('${lyrics.error!}\n点此重试', textAlign: TextAlign.center),
        ),
      );
    }
    if (lyrics.value['status'] == 'choose') {
      return Center(
        child: TextButton.icon(
          key: const Key('music-match-lyrics'),
          onPressed: () => chooseMusicLyrics(context, music),
          icon: const Icon(Icons.lyrics_outlined, size: 20),
          label: const Text('匹配这首歌的歌词'),
        ),
      );
    }
    final items = lines;
    if (items.isEmpty) {
      return Center(
        child: Text(
          lyrics.value['message'] as String? ??
              (music.available ? '等待歌曲信息与歌词' : '音乐响起，歌词就会出现在这里'),
          textAlign: TextAlign.center,
          style: MusicStyle.note,
        ),
      );
    }
    if (widget.compact) {
      final index = math.max(0, current);
      return TextButton(
        key: const Key('music-expand-lyrics'),
        onPressed: widget.onExpand,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              items[index]['text'] as String,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 18,
                height: 1.65,
                fontWeight: current >= 0 ? FontWeight.w500 : FontWeight.w400,
                color: current >= 0 ? MusicStyle.ink : MusicStyle.muted,
              ),
            ),
            if (index + 1 < items.length)
              Text(
                items[index + 1]['text'] as String,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                textAlign: TextAlign.center,
                style: MusicStyle.note,
              ),
          ],
        ),
      );
    }
    return Column(
      children: [
        Expanded(
          child: ShaderMask(
            blendMode: BlendMode.dstIn,
            shaderCallback: (bounds) => const LinearGradient(
              begin: Alignment.topCenter,
              end: Alignment.bottomCenter,
              colors: [
                Colors.transparent,
                Colors.white,
                Colors.white,
                Colors.transparent,
              ],
              stops: [0, .09, .88, 1],
            ).createShader(bounds),
            child: NotificationListener<ScrollNotification>(
              onNotification: (event) {
                final userScroll =
                    event is UserScrollNotification &&
                    event.direction != ScrollDirection.idle;
                final dragging =
                    event is ScrollStartNotification &&
                    event.dragDetails != null;
                if ((userScroll || dragging) && following) {
                  setState(() => following = false);
                }
                return false;
              },
              child: SingleChildScrollView(
                key: const Key('music-lyrics-scroll'),
                controller: scroll,
                padding: const EdgeInsets.symmetric(vertical: 52),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    for (var i = 0; i < items.length; i++)
                      InkWell(
                        key: ValueKey('music-lyric-$i'),
                        borderRadius: BorderRadius.circular(8),
                        onTap: () async {
                          final aligned = await showMusicLyricActions(
                            context,
                            music,
                            items[i],
                            widget.onQuote,
                          );
                          if (mounted && aligned) {
                            setState(() => following = true);
                            _tick();
                            _follow();
                          }
                        },
                        child: Padding(
                          key: keys.putIfAbsent(i, () => GlobalKey()),
                          padding: const EdgeInsets.symmetric(
                            vertical: 10,
                            horizontal: 16,
                          ),
                          child: Text(
                            items[i]['text'] as String,
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              fontSize: current == i ? 21 : 18,
                              height: 1.6,
                              fontWeight: current == i
                                  ? FontWeight.w500
                                  : FontWeight.w400,
                              color: current == i
                                  ? MusicStyle.ink
                                  : MusicStyle.muted,
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
        if (!following && current >= 0)
          TextButton(
            onPressed: () {
              setState(() => following = true);
              _follow();
            },
            child: const Text('回到当前歌词'),
          )
        else
          Text(
            lyrics.value['truncated'] == true
                ? '歌词较长，当前显示前 500 行'
                : music.lyricsCalibrated
                ? '歌词已手动对齐 · 切歌或跳转后可重新校准'
                : music.positionMs() == null && lyrics.value['timed'] == true
                ? '暂未同步到进度 · 可点歌词手动对齐'
                : '歌词自动跟随 · 点一句和 TA 聊聊',
            style: MusicStyle.note.copyWith(fontSize: 12),
            textAlign: TextAlign.center,
          ),
      ],
    );
  }
}
